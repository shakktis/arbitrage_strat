from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import requests

def _get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def list_series(base_url: str) -> List[Dict[str, Any]]:
    # Docs: GET /series returns a list of series objects (public market data). :contentReference[oaicite:5]{index=5}
    data = _get_json(f"{base_url}/series")
    return data.get("series", [])

def choose_fed_series(series: List[Dict[str, Any]]) -> str:
    # Score by title keywords
    keywords = ["fomc", "fed", "federal reserve", "interest rate", "fed funds"]
    best = None
    for s in series:
        title = (s.get("title") or "").lower()
        ticker = s.get("ticker") or ""
        if not ticker:
            continue
        score = 0
        for kw in keywords:
            if kw in title:
                score += 1
        if score > 0:
            if best is None or score > best[0]:
                best = (score, ticker, s.get("title") or "")
    if best is None:
        raise RuntimeError("Could not auto-find a Fed/FOMC-related Kalshi series. You may need to set it manually.")
    return best[1]

def auto_find_fed_series_ticker(base_url: str) -> str:
    series = list_series(base_url)
    return choose_fed_series(series)
