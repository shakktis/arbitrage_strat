from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class Config:
    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    kalshi_series_ticker: str = "KXFEDDECISION"
    meeting_decision_date: date = date(2025, 1, 29)
    effective_from_date: date = date(2025, 1, 30)

    # Pre-meeting “anchor” rate. Start simple with the midpoint of the target range.
    # For Jan 2025, a common assumption is 5.375 (midpoint of 5.25–5.50).
    pre_meeting_rate_mid: float = 5.375
    rate_step: float = 0.25

    # Futures contract month used to represent the “meeting month”
    futures_year: int = 2025
    futures_month: int = 1  # Jan

    # Also fetch prior month as a sanity check (optional use)
    prior_futures_year: int = 2024
    prior_futures_month: int = 12  # Dec

    # Signal threshold: how far probabilities must differ to flag an “edge”
    edge_threshold: float = 0.03

    # SQLite file
    sqlite_path: str = "data.sqlite"
