# src/futures_client.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
import requests
import yfinance as yf

_MONTH_CODE = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"
}

def fed_funds_futures_symbol(year: int, month: int) -> str:
    yy = str(year)[-2:]
    code = _MONTH_CODE[int(month)]
    return f"ZQ{code}{yy}.CBT"

@dataclass(frozen=True)
class FuturesQuote:
    symbol: str
    last_close: Optional[float]
    used_symbol: Optional[str]
    attempted: List[str]
    error: Optional[str] = None

    @property
    def implied_month_avg_rate(self) -> Optional[float]:
        if self.last_close is None:
            return None
        return 100.0 - float(self.last_close)

def _last_close_from_yfinance(sym: str) -> Optional[float]:
    df = yf.download(sym, period="365d", interval="1d", progress=False, auto_adjust=False, threads=False)
    if df is None or df.empty:
        return None
    close = df.get("Close")
    if close is None:
        return None
    close = close.dropna()
    if close.empty:
        return None
    return float(close.iloc[-1])

def _last_close_from_yahoo_chart(sym: str) -> Optional[float]:
    # Direct Yahoo chart endpoint (bypasses yfinance failures).
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    params = {"range": "1y", "interval": "1d", "includePrePost": "false", "events": "div,splits"}
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, params=params, headers=headers, timeout=20)
    if r.status_code != 200:
        return None
    data = r.json()
    res = (((data or {}).get("chart") or {}).get("result") or [])
    if not res:
        return None
    quote = (((res[0].get("indicators") or {}).get("quote") or []))
    if not quote:
        return None
    closes = quote[0].get("close") or []
    # last non-null close
    for x in reversed(closes):
        if x is not None:
            return float(x)
    return None

def _candidates(symbol: str) -> List[str]:
    # Common Yahoo/CME quirks: sometimes futures are under 0-prefixed ticker.
    base = symbol.strip()
    out = []
    if base:
        out.append(base)
        out.append(f"0{base}")

    # Sometimes dropping the exchange suffix works (rare, but cheap to try)
    if base.endswith(".CBT"):
        no_ex = base.replace(".CBT", "")
        out.append(no_ex)
        out.append(f"0{no_ex}")

    # De-dupe while preserving order
    seen = set()
    uniq = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq

def fetch_last_close(symbol: str) -> FuturesQuote:
    attempted = _candidates(symbol)
    errs: List[str] = []

    for sym in attempted:
        try:
            v = _last_close_from_yfinance(sym)
            if v is not None:
                return FuturesQuote(symbol=symbol, last_close=v, used_symbol=sym, attempted=attempted, error=None)
        except Exception as e:
            errs.append(f"yfinance({sym}): {e}")

        try:
            v = _last_close_from_yahoo_chart(sym)
            if v is not None:
                return FuturesQuote(symbol=symbol, last_close=v, used_symbol=sym, attempted=attempted, error=None)
        except Exception as e:
            errs.append(f"chart({sym}): {e}")

    return FuturesQuote(
        symbol=symbol,
        last_close=None,
        used_symbol=None,
        attempted=attempted,
        error=" | ".join(errs) if errs else "No data from yfinance or Yahoo chart endpoint.",
    )

def fetch_quotes(symbols: Dict[str, str]) -> Dict[str, FuturesQuote]:
    out: Dict[str, FuturesQuote] = {}
    for k, sym in symbols.items():
        out[k] = fetch_last_close(sym)
    return out
