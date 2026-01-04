# src/kalshi_client.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
import requests

@dataclass(frozen=True)
class KalshiMarket:
    ticker: str
    title: str
    yes_bid: Optional[int]
    yes_ask: Optional[int]
    last_price: Optional[int]
    status: str

    @property
    def mid_prob(self) -> Optional[float]:
        if self.yes_bid is not None and self.yes_ask is not None:
            if self.yes_bid >= 0 and self.yes_ask >= 0:
                return ((self.yes_bid + self.yes_ask) / 2.0) / 100.0
        if self.last_price is not None and self.last_price >= 0:
            return self.last_price / 100.0
        return None

def _get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Dict[str, Any]:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def list_events(base_url: str, series_ticker: str, status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"series_ticker": series_ticker, "limit": limit}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        data = _get_json(f"{base_url}/events", params=params)
        batch = data.get("events", [])
        events.extend(batch)
        cursor = data.get("cursor") or ""
        if not cursor:
            break
    return events

def _parse_event_datetime(e: Dict[str, Any]) -> Optional[datetime]:
    # Try a bunch of possible keys across Kalshi event schemas
    keys = [
        "strike_date", "strike_time", "strike_datetime",
        "close_time", "close_date", "settlement_time",
        "end_date", "end_time",
        "start_date", "start_time",
    ]
    for k in keys:
        v = e.get(k)
        if not v:
            continue
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                continue
    return None

def choose_event_for_date(events: List[Dict[str, Any]], target: date) -> Tuple[str, str]:
    # Use noon to reduce timezone-edge weirdness
    target_dt = datetime(target.year, target.month, target.day, 12, 0, 0)

    best = None
    for e in events:
        dt = _parse_event_datetime(e)
        if dt is None:
            continue
        dist = abs((dt - target_dt).total_seconds())
        if best is None or dist < best[0]:
            best = (dist, e.get("event_ticker"), e.get("title") or "")

    if best is None or not best[1]:
        raise RuntimeError("Could not find a suitable event for the target date in this series.")
    return best[1], best[2]

def get_event_with_markets(base_url: str, event_ticker: str) -> Dict[str, Any]:
    return _get_json(f"{base_url}/events/{event_ticker}", params={"with_nested_markets": "true"})

def parse_markets(event_payload: Dict[str, Any]) -> List[KalshiMarket]:
    event = event_payload.get("event") or {}
    markets = event.get("markets") or event_payload.get("markets") or []
    out: List[KalshiMarket] = []
    for m in markets:
        out.append(
            KalshiMarket(
                ticker=m.get("ticker", ""),
                title=m.get("title", ""),
                yes_bid=m.get("yes_bid"),
                yes_ask=m.get("yes_ask"),
                last_price=m.get("last_price"),
                status=m.get("status", ""),
            )
        )
    return out

def classify_fed_decision_market_title(title: str) -> Optional[Tuple[str, int]]:
    t = title.lower()

    if "maintain" in t or "no change" in t or "holds" in t or "hold" in t:
        return ("HOLD", 0)

    if "cut" in t:
        for bps in (25, 50, 75, 100):
            if f"{bps}" in t:
                return ("CUT", bps)
        return ("CUT", 25)

    if "hike" in t or "raise" in t:
        for bps in (25, 50, 75, 100):
            if f"{bps}" in t:
                return ("HIKE", bps)
        return ("HIKE", 25)

    return None
