# src/kalshi_client.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import requests

@dataclass(frozen=True)
class KalshiMarket:
    ticker: str
    title: str
    yes_bid: Optional[int]     # cents
    yes_ask: Optional[int]     # cents
    last_price: Optional[int]  # cents
    status: str

    @property
    def mid_prob(self) -> Optional[float]:
        """
        IMPORTANT: only trust live quotes (yes_bid/yes_ask). Do NOT fall back to last_price,
        because last_price is often stale and can sit at 50 for many outcomes.
        """
        if self.yes_bid is None or self.yes_ask is None:
            return None
        if self.yes_bid < 0 or self.yes_ask < 0:
            return None
        return ((self.yes_bid + self.yes_ask) / 2.0) / 100.0

def _get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Dict[str, Any]:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

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

