from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple
import calendar

@dataclass(frozen=True)
class FuturesImpliedProbs:
    implied_post_rate: float
    probs: Dict[str, float]

def days_in_month(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]

def implied_post_meeting_rate(
    month_avg_rate: float,
    pre_rate: float,
    meeting_month_year: int,
    meeting_month: int,
    effective_from: date,
) -> float:
    n = days_in_month(meeting_month_year, meeting_month)
    n_pre = effective_from.day - 1
    n_post = n - n_pre
    if n_post <= 0:
        raise ValueError("effective_from must be within the contract month and not after month end.")
    return (month_avg_rate * n - pre_rate * n_pre) / n_post

def bracket_probs(implied: float, base_mid: float, step: float = 0.25) -> Dict[str, float]:
    hold = base_mid
    cut25 = base_mid - step
    hike25 = base_mid + step

    if implied <= cut25:
        return {"CUT25": 1.0, "HOLD": 0.0, "HIKE25": 0.0}
    if implied >= hike25:
        return {"CUT25": 0.0, "HOLD": 0.0, "HIKE25": 1.0}

    if implied < hold:
        p_hold = (implied - cut25) / step
        return {"CUT25": 1.0 - p_hold, "HOLD": p_hold, "HIKE25": 0.0}

    p_hike = (implied - hold) / step
    return {"CUT25": 0.0, "HOLD": 1.0 - p_hike, "HIKE25": p_hike}

def futures_to_probs(
    month_avg_rate: float,
    pre_rate_mid: float,
    meeting_month_year: int,
    meeting_month: int,
    effective_from: date,
    step: float = 0.25,
) -> FuturesImpliedProbs:
    post = implied_post_meeting_rate(
        month_avg_rate=month_avg_rate,
        pre_rate=pre_rate_mid,
        meeting_month_year=meeting_month_year,
        meeting_month=meeting_month,
        effective_from=effective_from,
    )
    probs = bracket_probs(implied=post, base_mid=pre_rate_mid, step=step)
    return FuturesImpliedProbs(implied_post_rate=post, probs=probs)

def kalshi_probs_to_action_buckets(kalshi_probs: Dict[Tuple[str, int], float]) -> Dict[str, float]:
    cut25 = kalshi_probs.get(("CUT", 25), 0.0)
    hold = kalshi_probs.get(("HOLD", 0), 0.0)
    hike25 = kalshi_probs.get(("HIKE", 25), 0.0)
    return {"CUT25": cut25, "HOLD": hold, "HIKE25": hike25}
