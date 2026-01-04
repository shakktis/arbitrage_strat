from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict
import yfinance as yf

_MONTH_CODE = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"
}

def fed_funds_futures_symbol(year: int, month: int) -> str:
    yy = str(year)[-2:]
    code = _MONTH_CODE[month]
    return f"ZQ{code}{yy}.CBT"

@dataclass(frozen=True)
class FuturesQuote:
    symbol: str
    last_close: Optional[float]

    @property
    def implied_month_avg_rate(self) -> Optional[float]:
        if self.last_close is None:
            return None
        return 100.0 - float(self.last_close)

def fetch_last_close(symbol: str) -> FuturesQuote:
    t = yf.Ticker(symbol)
    hist = t.history(period="7d", interval="1d")
    if hist is None or hist.empty:
        return FuturesQuote(symbol=symbol, last_close=None)
    last_close = float(hist["Close"].dropna().iloc[-1])
    return FuturesQuote(symbol=symbol, last_close=last_close)

def fetch_quotes(symbols: Dict[str, str]) -> Dict[str, FuturesQuote]:
    out: Dict[str, FuturesQuote] = {}
    for k, sym in symbols.items():
        out[k] = fetch_last_close(sym)
    return out
