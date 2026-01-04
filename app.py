# app.py  (drop-in replacement)
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.fomc_calendar import get_upcoming_meeting
from src.kalshi_discovery import rank_fomc_series
from src.kalshi_client import (
    list_events,
    choose_event_for_date,
    get_event_with_markets,
    parse_markets,
    classify_fed_decision_market_title,
)
from src.futures_client import fed_funds_futures_symbol, fetch_quotes
from src.model import futures_to_probs, kalshi_probs_to_action_buckets
from src import db as dbmod

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
SQLITE_PATH = "data.sqlite"

st.set_page_config(page_title="Kalshi vs Fed Funds Futures", layout="wide")
st_autorefresh(interval=15_000, key="refresh")
st.title("LIVE: Kalshi vs Fed Funds Futures")

conn = dbmod.connect(SQLITE_PATH)
dbmod.init(conn)

now_utc_dt = datetime.now(timezone.utc)
today_utc = now_utc_dt.date()
now_utc_iso = now_utc_dt.isoformat()

# Keep calendar auto, but allow manual override if you want
next_meeting = get_upcoming_meeting(today=today_utc)
auto_meeting_decision_date = next_meeting.end_date
auto_effective_from = (datetime(next_meeting.year, next_meeting.month, next_meeting.end_day) + timedelta(days=1)).date()

auto_series_candidates = rank_fomc_series(KALSHI_BASE, top_n=12)

auto_fut_y, auto_fut_m = next_meeting.year, next_meeting.month
auto_prior_y, auto_prior_m = (auto_fut_y - 1, 12) if auto_fut_m == 1 else (auto_fut_y, auto_fut_m - 1)

default_meeting_sym = fed_funds_futures_symbol(auto_fut_y, auto_fut_m)
default_prior_sym = fed_funds_futures_symbol(auto_prior_y, auto_prior_m)

with st.sidebar:
    st.subheader("Mode")
    auto_mode = st.checkbox("AUTO (meeting date)", value=True)

    if auto_mode:
        st.subheader("Next meeting (auto)")
        st.write(f"{next_meeting.start_date} to {next_meeting.end_date}")
        meeting_date = st.date_input("Meeting decision date", value=auto_meeting_decision_date)
        effective_from = st.date_input("Effective from (day after decision)", value=auto_effective_from)
        fut_y = int(st.number_input("Futures year", value=int(auto_fut_y), step=1))
        fut_m = int(st.number_input("Futures month (1-12)", value=int(auto_fut_m), step=1))
        prior_fut_y = int(st.number_input("Prior futures year", value=int(auto_prior_y), step=1))
        prior_fut_m = int(st.number_input("Prior futures month (1-12)", value=int(auto_prior_m), step=1))
    else:
        meeting_date = st.date_input("Meeting decision date", value=date(2025, 1, 29))
        effective_from = st.date_input("Effective from (day after decision)", value=date(2025, 1, 30))
        fut_y = int(st.number_input("Futures year", value=2025, step=1))
        fut_m = int(st.number_input("Futures month (1-12)", value=1, step=1))
        prior_fut_y = int(st.number_input("Prior futures year", value=2024, step=1))
        prior_fut_m = int(st.number_input("Prior futures month (1-12)", value=12, step=1))

    st.subheader("Kalshi series")
    st.caption("Force the correct one if needed. For Fed decision, use KXFEDDECISION.")
    series_override = st.text_input("Force Kalshi series ticker", value="KXFEDDECISION")

    st.subheader("Futures symbols (override if Yahoo fails)")
    meeting_sym_default = fed_funds_futures_symbol(fut_y, fut_m)
    prior_sym_default = fed_funds_futures_symbol(prior_fut_y, prior_fut_m)
    meeting_sym = st.text_input("Meeting-month futures symbol", value=meeting_sym_default)
    prior_sym = st.text_input("Prior-month futures symbol", value=prior_sym_default)

    edge_threshold = float(st.number_input("Edge threshold", value=0.03, step=0.01))
    step = float(st.number_input("Rate step (25bp = 0.25)", value=0.25, step=0.125))

def _try_kalshi_for_series(series_ticker: str, target_date: date):
    events = list_events(KALSHI_BASE, series_ticker=series_ticker, status=None)
    event_ticker, event_title = choose_event_for_date(events, target=target_date)
    payload = get_event_with_markets(KALSHI_BASE, event_ticker=event_ticker)
    markets = parse_markets(payload)

    probs = {}
    rows = []
    for m in markets:
        cls = classify_fed_decision_market_title(m.title)
        p = m.mid_prob
        if cls is not None and p is not None:
            probs[cls] = p
        rows.append({"ticker": m.ticker, "title": m.title, "status": m.status, "mid_prob": p})

    return series_ticker, event_ticker, event_title, probs, pd.DataFrame(rows)

@st.cache_data(ttl=15)
def load_kalshi_snapshot(target_date: date, forced_series: str):
    return _try_kalshi_for_series(forced_series.strip(), target_date)

@st.cache_data(ttl=15)
def load_futures_quotes(meeting_symbol: str, prior_symbol: str):
    return fetch_quotes({"meeting_month": meeting_symbol.strip(), "prior_month": prior_symbol.strip()})

# --- Kalshi ---
try:
    series_used, event_ticker, event_title, kalshi_probs_raw, kalshi_markets_df = load_kalshi_snapshot(
        meeting_date, series_override
    )
except Exception as e:
    st.error(f"Kalshi error: {e}")
    st.stop()

# --- Futures ---
quotes = load_futures_quotes(meeting_sym, prior_sym)
q_meeting = quotes["meeting_month"]
q_prior = quotes["prior_month"]

meeting_month_avg = q_meeting.implied_month_avg_rate
prior_month_avg = q_prior.implied_month_avg_rate

if meeting_month_avg is None or prior_month_avg is None:
    st.error("Missing futures prices from Yahoo for meeting/prior month.")
    st.write("Meeting-month debug:", {"requested": q_meeting.symbol, "used": q_meeting.used_symbol, "attempted": q_meeting.attempted, "error": q_meeting.error})
    st.write("Prior-month debug:", {"requested": q_prior.symbol, "used": q_prior.used_symbol, "attempted": q_prior.attempted, "error": q_prior.error})
    st.stop()

pre_rate_mid = float(prior_month_avg)

fut = futures_to_probs(
    month_avg_rate=float(meeting_month_avg),
    pre_rate_mid=pre_rate_mid,
    meeting_month_year=int(fut_y),
    meeting_month=int(fut_m),
    effective_from=effective_from,
    step=float(step),
)

col1, col2 = st.columns([1.2, 1])

with col1:
    st.markdown(f"**Kalshi series used:** `{series_used}`")
    st.markdown(f"**Kalshi event:** `{event_ticker}`  \n**Title:** {event_title}")
    st.dataframe(kalshi_markets_df.sort_values(["mid_prob"], ascending=False), use_container_width=True, height=360)

with col2:
    st.subheader("Futures inputs")
    st.write(
        {
            "meeting_month_requested": q_meeting.symbol,
            "meeting_month_used": q_meeting.used_symbol,
            "meeting_month_last_close": q_meeting.last_close,
            "meeting_month_implied_avg_rate": meeting_month_avg,
            "prior_month_requested": q_prior.symbol,
            "prior_month_used": q_prior.used_symbol,
            "prior_month_last_close": q_prior.last_close,
            "prior_month_implied_avg_rate (anchor)": prior_month_avg,
        }
    )
    st.subheader("Implied post-meeting rate (from futures)")
    st.metric("Implied post-meeting rate", f"{fut.implied_post_rate:.3f}%")

kalshi_actions = kalshi_probs_to_action_buckets(kalshi_probs_raw)

kalshi_df = pd.DataFrame([{"Outcome": k, "Kalshi": float(v)} for k, v in kalshi_actions.items()]).set_index("Outcome")
fut_df = pd.DataFrame([{"Outcome": k, "Futures": float(v)} for k, v in fut.probs.items()]).set_index("Outcome")

cmp = kalshi_df.join(fut_df, how="outer").fillna(0.0)
cmp["Edge (Futures - Kalshi)"] = cmp["Futures"] - cmp["Kalshi"]

st.subheader("Probability comparison (Kalshi vs futures-implied)")
st.dataframe(cmp, use_container_width=True)

signals = []
for outcome, row in cmp.iterrows():
    edge = float(row["Edge (Futures - Kalshi)"])
    if edge > edge_threshold:
        signals.append((outcome, "Kalshi looks cheap", edge))
    elif edge < -edge_threshold:
        signals.append((outcome, "Kalshi looks rich", edge))

st.subheader("Signals")
if signals:
    st.table(pd.DataFrame(signals, columns=["Outcome", "Signal", "Edge"]))
else:
    st.write("No signals beyond threshold.")

dbmod.insert_snapshot(conn, now_utc_iso, "kalshi", {f"kalshi_{k}": v for k, v in kalshi_actions.items()})
dbmod.insert_snapshot(conn, now_utc_iso, "futures", {f"fut_{k}": v for k, v in fut.probs.items()})
dbmod.insert_snapshot(conn, now_utc_iso, "misc", {"implied_post_rate": fut.implied_post_rate})
