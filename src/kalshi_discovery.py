# src/kalshi_discovery.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import requests

def _get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def list_series(base_url: str) -> List[Dict[str, Any]]:
    data = _get_json(f"{base_url}/series")
    return data.get("series", [])

def rank_fomc_series(base_url: str, top_n: int = 12) -> List[str]:
    series = list_series(base_url)

    all_tickers = []
    for s in series:
        t = (s.get("ticker") or "").strip()
        if t:
            all_tickers.append(t)

    # Hard-pin the one we KNOW is the Fed decision series
    pinned = []
    if "KXFEDDECISION" in all_tickers:
        pinned.append("KXFEDDECISION")

    weights = {
        "kxfeddecision": 999,     # if it appears in text anywhere, slam-dunk it
        "fomc": 50,
        "fed decision": 40,
        "rate decision": 35,
        "federal open market": 30,
        "meeting": 20,
        "decision": 20,
        "target rate": 15,
        "federal reserve": 10,
        "fed funds": 10,
        "interest rate": 8,
        "policy rate": 8,
        "kxfed": 25,              # favour tickers that look like KX Fed series
    }

    scored: List[Tuple[int, str]] = []
    for s in series:
        ticker = (s.get("ticker") or "").strip()
        title = (s.get("title") or "").strip()
        if not ticker:
            continue

        text = (title + " " + ticker).lower()
        score = 0
        for kw, w in weights.items():
            if kw in text:
                score += w

        # extra boost for tickers that start with KXFED (often the macro series)
        if ticker.lower().startswith("kxfed"):
            score += 30

        if score > 0:
            scored.append((score, ticker))

    scored.sort(key=lambda x: x[0], reverse=True)

    ranked = pinned + [t for _, t in scored if t not in pinned]
    return ranked[:top_n]
