from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from typing import Optional, Dict, Any
import re
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.kalshi_client import get_event_with_markets, parse_markets
from src.futures_client import fed_funds_futures_symbol, fetch_quotes
from src.model import futures_to_probs
from src import db as dbmod
from src.link_parser import extract_kalshi_event_slug, slug_to_event_ticker, slug_to_year_month

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
SQLITE_PATH = "data.sqlite"

st.set_page_config(page_title="Kalshi vs Fed Funds Futures", layout="wide")
st_autorefresh(interval=15_000, key="refresh")
st.title("Kalshi vs Fed Funds Futures (paste-link mode)")

conn = dbmod.connect(SQLITE_PATH)
dbmod.init(conn)

now_utc_dt = datetime.now(timezone.utc)
now_utc_iso = now_utc_dt.isoformat()

def _parse_event_time(event: Dict[str, Any]) -> Optional[datetime]:
    for k in ["strike_time", "strike_date", "close_time", "settlement_time", "end_time", "start_time"]:
        v = event.get(k)
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                continue
    return None

@st.cache_data(ttl=60)
def load_kalshi_event(event_ticker: str) -> Dict[str, Any]:
    return get_event_with_markets(KALSHI_BASE, event_ticker=event_ticker)

@st.cache_data(ttl=60)
def load_futures_quote(symbol: str):
    return fetch_quotes({"meeting_month": symbol.strip()})["meeting_month"]

_BPS_RE = re.compile(r"(\d{1,3})\s*(?:bp|bps|basis\s*points?)\b", re.IGNORECASE)

def _infer_move_bps_from_kalshi(market_ticker: str, title: str, rep_gt25_bps: int) -> Optional[int]:
    tkr = (market_ticker or "").upper()

    # Ticker-based rules
    if tkr.endswith("-H0") or tkr.endswith("-0"):
        return 0
    if tkr.endswith("-C25"):
        return -25
    if tkr.endswith("-H25"):
        return +25
    if tkr.endswith("-C26"):
        return -int(rep_gt25_bps)
    if tkr.endswith("-H26"):
        return +int(rep_gt25_bps)

    # Title fallbacks
    tt = (title or "").lower()
    if "no change" in tt or "unchanged" in tt or re.search(r"\b0\s*(bp|bps|basis)\b", tt):
        return 0

    m = _BPS_RE.search(tt)
    bps = int(m.group(1)) if m else None

    if any(x in tt for x in ["cut", "decrease", "lower", "reduce"]):
        if bps is None:
            return None
        if ">" in tt or "more than" in tt:
            return -int(rep_gt25_bps)
        return -bps

    if any(x in tt for x in ["hike", "raise", "increase", "higher"]):
        if bps is None:
            return None
        if ">" in tt or "more than" in tt:
            return +int(rep_gt25_bps)
        return +bps

    return None

with st.sidebar:
    st.subheader("Inputs (paste-link mode)")
    kalshi_link = st.text_input(
        "Kalshi event link",
        value="https://kalshi.com/markets/kxfeddecision/fed-meeting/kxfeddecision-26jan",
        help="Paste the Kalshi event page link for the meeting you want."
    )

    step = float(st.number_input("Rate step (25bp = 0.25)", value=0.25, step=0.125))
    max_move_bps = int(st.number_input("Max move bucket (bps)", value=100, step=25))

    st.subheader("Basis-point view settings")
    rep_gt25_bps = int(st.number_input("Representative move for '>25bps' buckets", value=50, step=25))
    bp_edge_threshold = float(st.number_input("BP edge threshold", value=10.0, step=5.0))

    st.subheader("Advanced (manual overrides)")
    override_meeting_symbol = st.text_input("Override meeting-month futures symbol (optional)", value="")
    manual_r0 = st.text_input("Manual R0 (EFFR) override, percent", value="")

# --- Parse Kalshi link -> event ticker
try:
    slug = extract_kalshi_event_slug(kalshi_link)
    event_ticker = slug_to_event_ticker(slug)
    slug_year, slug_month = slug_to_year_month(slug)
except Exception as e:
    st.error(f"Kalshi link parse error: {e}")
    st.stop()

# --- Pull Kalshi event + markets
try:
    payload = load_kalshi_event(event_ticker)
    event = payload.get("event") or {}
    event_time = _parse_event_time(event)
    markets = parse_markets(payload)
except Exception as e:
    st.error(f"Kalshi API error for {event_ticker}: {e}")
    st.stop()

# Meeting decision date:
if event_time is not None:
    meeting_decision_date = event_time.date()
else:
    meeting_decision_date = date(slug_year, slug_month, 1)

effective_from = meeting_decision_date + timedelta(days=1)

# Meeting month/year futures ticker (by date)
fut_y = meeting_decision_date.year
fut_m = meeting_decision_date.month
meeting_sym_default = fed_funds_futures_symbol(fut_y, fut_m)
meeting_sym = override_meeting_symbol.strip() or meeting_sym_default

# --- Pull meeting-month futures
q_meeting = load_futures_quote(meeting_sym)
meeting_month_avg = q_meeting.implied_month_avg_rate
if meeting_month_avg is None:
    st.error("Missing meeting-month futures price from Yahoo.")
    st.write("Meeting-month debug:", {"requested": q_meeting.symbol, "used": q_meeting.used_symbol, "attempted": q_meeting.attempted, "error": q_meeting.error})
    st.stop()

# --- Manual R0 required
if not manual_r0.strip():
    st.error("Type a Manual R0 (EFFR) in the sidebar (e.g., 3.64).")
    st.stop()
try:
    r0 = float(manual_r0.strip())
except Exception:
    st.error("Manual R0 (EFFR) must be a number like 3.64 (no % sign).")
    st.stop()

# --- Futures -> implied probabilities (multi-bucket)
fut = futures_to_probs(
    month_avg_rate=float(meeting_month_avg),
    pre_rate_mid=float(r0),
    meeting_month_year=int(fut_y),
    meeting_month=int(fut_m),
    effective_from=effective_from,
    step=float(step),
    max_move_bps=int(max_move_bps),
)

# --- Parse Kalshi markets (show quotes + compute probabilities ONLY from bid/ask mid)
rows = []
kalshi_move_probs_raw: Dict[int, float] = {}  # move_bps -> raw prob mass (from live quotes only)
for m in markets:
    p = m.mid_prob  # only from bid/ask now (see kalshi_client.py)
    mv = _infer_move_bps_from_kalshi(m.ticker, m.title, rep_gt25_bps=rep_gt25_bps)
    rows.append(
        {
            "ticker": m.ticker,
            "title": m.title,
            "yes_bid": m.yes_bid,
            "yes_ask": m.yes_ask,
            "last_price": m.last_price,
            "mid_prob(live)": p,
            "move_bps": mv,
        }
    )
    if p is None or mv is None:
        continue
    kalshi_move_probs_raw[mv] = kalshi_move_probs_raw.get(mv, 0.0) + float(p)

kalshi_markets_df = pd.DataFrame(rows)

live_mids = [r["mid_prob(live)"] for r in rows if r.get("mid_prob(live)") is not None]

if len(live_mids) < 2:
    st.warning(
        "Kalshi has too few live bid/ask mids to infer probabilities reliably. "
        "This usually means the market is illiquid right now. "
        "We will still show the futures-implied side."
    )
else:
    spread = max(live_mids) - min(live_mids)
    if spread <= 0.01:  # 1 cent in probability terms
        st.warning(
            "Kalshi live mids are essentially flat across outcomes (within ~1¢). "
            "This usually indicates illiquidity or placeholder quoting (e.g., many contracts stuck near 0.50). "
            "Normalised 'probabilities' may be uninformative; rely on the basis-point view or wait for tighter quotes."
        )

st.caption(f"Kalshi live-mid spread across outcomes: { (max(live_mids)-min(live_mids)) if live_mids else 'N/A' }")

# --- Liquidity diagnostics
kalshi_prob_sum = sum(kalshi_move_probs_raw.values())
num_live = sum(1 for v in kalshi_move_probs_raw.values() if v > 0)

if kalshi_prob_sum == 0:
    st.warning("Kalshi has no live bid/ask quotes (mid prices missing). Showing futures only. "
               "Check yes_bid/yes_ask columns; last_price can be stale and is NOT used.")
    kalshi_move_probs = {}
else:
    # Normalise so distribution sums to 1 (presentation-safe)
    kalshi_move_probs = {mv: p / kalshi_prob_sum for mv, p in kalshi_move_probs_raw.items()}

# --- Basis-point view: expected move from Kalshi (normalised)
kalshi_expected_move_bps = sum(mv * prob for mv, prob in kalshi_move_probs.items()) if kalshi_move_probs else 0.0
kalshi_expected_post_rate = r0 + kalshi_expected_move_bps / 100.0

# --- Futures basis-point view
futures_expected_post_rate = float(fut.implied_post_rate)
futures_expected_move_bps = (futures_expected_post_rate - r0) * 100.0
bp_edge = futures_expected_move_bps - kalshi_expected_move_bps

# --- Probability view (labels from move bps)
def _label_from_move(mv: int) -> str:
    if mv == 0:
        return "HOLD"
    if mv < 0:
        return f"CUT{abs(mv)}"
    return f"HIKE{mv}"

kalshi_actions = {_label_from_move(mv): prob for mv, prob in kalshi_move_probs.items()}
fut_actions = fut.probs

all_outcomes = sorted(set(kalshi_actions.keys()) | set(fut_actions.keys()))
cmp_prob = pd.DataFrame(index=all_outcomes, columns=["Kalshi", "Futures"], data=0.0)
for k, v in kalshi_actions.items():
    cmp_prob.loc[k, "Kalshi"] = float(v)
for k, v in fut_actions.items():
    cmp_prob.loc[k, "Futures"] = float(v)
cmp_prob["Edge (Futures - Kalshi)"] = cmp_prob["Futures"] - cmp_prob["Kalshi"]

# --- Layout
col1, col2 = st.columns([1.2, 1])

with col1:
    st.markdown(f"**Kalshi event ticker:** `{event_ticker}`")
    st.markdown(f"**Meeting decision date:** `{meeting_decision_date}`")
    st.markdown(f"**Effective from (assumed):** `{effective_from}`")
    st.dataframe(kalshi_markets_df, use_container_width=True, height=360)

with col2:
    st.subheader("Inputs used")
    st.write(
        {
            "meeting_month_symbol": q_meeting.symbol,
            "meeting_month_used": q_meeting.used_symbol,
            "meeting_month_last_close": q_meeting.last_close,
            "meeting_month_implied_avg_rate (Ravg)": meeting_month_avg,
            "manual_R0 (EFFR)": r0,
            "rep_gt25_bps": rep_gt25_bps,
            "kalshi_prob_sum (live only)": kalshi_prob_sum,
        }
    )

    st.subheader("Implied post-meeting rate (from futures)")
    st.metric("E[R1] (futures implied)", f"{futures_expected_post_rate:.3f}%")

    st.subheader("Basis-point summary")
    st.metric("Futures implied move (bps)", f"{futures_expected_move_bps:.1f}")
    st.metric("Kalshi implied move (bps)", f"{kalshi_expected_move_bps:.1f}")
    st.metric("Edge (futures - kalshi) (bps)", f"{bp_edge:.1f}")

# --- Basis-point comparison table
bp_table = pd.DataFrame(
    {
        "Implied move (bps)": {
            "Kalshi (expected)": kalshi_expected_move_bps,
            "Futures (expected)": futures_expected_move_bps,
            "Edge (Futures - Kalshi)": bp_edge,
        },
        "Implied post-meeting rate (%)": {
            "Kalshi (expected)": kalshi_expected_post_rate,
            "Futures (expected)": futures_expected_post_rate,
            "Edge (Futures - Kalshi)": (futures_expected_post_rate - kalshi_expected_post_rate),
        }
    }
)

st.subheader("Basis-point comparison")
st.dataframe(bp_table, use_container_width=True)

st.subheader("Probability comparison (Kalshi vs futures-implied)")
st.dataframe(cmp_prob, use_container_width=True)

st.subheader("Signals (basis points)")
if abs(bp_edge) >= bp_edge_threshold:
    if bp_edge > 0:
        st.write(f"**Signal:** Futures imply a larger move than Kalshi by **{bp_edge:.1f} bps**.")
    else:
        st.write(f"**Signal:** Kalshi implies a larger move than futures by **{-bp_edge:.1f} bps**.")
else:
    st.write("No BP signal beyond threshold.")

# --- Log
dbmod.insert_snapshot(conn, now_utc_iso, "kalshi_bp", {"kalshi_expected_move_bps": kalshi_expected_move_bps, "kalshi_expected_post_rate": kalshi_expected_post_rate})
dbmod.insert_snapshot(conn, now_utc_iso, "futures_bp", {"futures_expected_move_bps": futures_expected_move_bps, "futures_expected_post_rate": futures_expected_post_rate, "bp_edge": bp_edge})
