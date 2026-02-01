# src/model.py  (FULL DROP-IN)
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Tuple
import calendar
import math

@dataclass(frozen=True)
class FuturesImpliedProbs:
    implied_post_rate: float
    probs: Dict[str, float]  # e.g. {"CUT25": 0.7, "CUT50": 0.3, ...}

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
    n_pre = max(0, effective_from.day - 1)
    n_post = n - n_pre
    if n_post <= 0:
        raise ValueError("effective_from must be inside the contract month (day after meeting decision).")
    return (month_avg_rate * n - pre_rate * n_pre) / n_post

def _label_for_step(k: int, step_bps: int) -> str:
    if k == 0:
        return "HOLD"
    bps = abs(k) * step_bps
    return f"CUT{bps}" if k < 0 else f"HIKE{bps}"

def _build_grid_rates(base: float, step: float, max_steps: int) -> Dict[int, float]:
    # k -> rate
    return {k: base + k * step for k in range(-max_steps, max_steps + 1)}

def bracket_probs_multi(
    implied: float,
    base: float,
    step: float = 0.25,
    max_move_bps: int = 100,
) -> Dict[str, float]:
    """
    Expand outcomes beyond +/-25bp by bracketing implied rate between nearest grid points.

    - Grid points: base + k*step, for k in [-max_steps..max_steps]
    - If implied is between k and k+1: interpolate between those two only.
    """
    step_bps = int(round(step * 100))  # 0.25 -> 25
    if step_bps <= 0:
        raise ValueError("step must be positive (e.g., 0.25).")

    max_steps = max(1, int(max_move_bps // step_bps))

    rates = _build_grid_rates(base=base, step=step, max_steps=max_steps)
    ks = sorted(rates.keys())
    grid = [rates[k] for k in ks]

    # Clip to boundary if outside
    if implied <= grid[0]:
        return {_label_for_step(ks[0], step_bps): 1.0}
    if implied >= grid[-1]:
        return {_label_for_step(ks[-1], step_bps): 1.0}

    # Find interval [k_i, k_{i+1}] containing implied
    # (Linear scan is fine, grid is tiny)
    for i in range(len(grid) - 1):
        lo, hi = grid[i], grid[i + 1]
        if lo <= implied <= hi:
            if math.isclose(hi, lo):
                return {_label_for_step(ks[i], step_bps): 1.0}
            p_hi = (implied - lo) / (hi - lo)  # weight on upper rate
            p_lo = 1.0 - p_hi

            out = {}
            if p_lo > 0:
                out[_label_for_step(ks[i], step_bps)] = float(p_lo)
            if p_hi > 0:
                out[_label_for_step(ks[i + 1], step_bps)] = float(p_hi)
            return out

    # Should never happen if logic above is correct
    return {}

def futures_to_probs(
    month_avg_rate: float,
    pre_rate_mid: float,
    meeting_month_year: int,
    meeting_month: int,
    effective_from: date,
    step: float = 0.25,
    max_move_bps: int = 100,
) -> FuturesImpliedProbs:
    post = implied_post_meeting_rate(
        month_avg_rate=month_avg_rate,
        pre_rate=pre_rate_mid,
        meeting_month_year=meeting_month_year,
        meeting_month=meeting_month,
        effective_from=effective_from,
    )
    probs = bracket_probs_multi(
        implied=post,
        base=pre_rate_mid,
        step=step,
        max_move_bps=max_move_bps,
    )
    return FuturesImpliedProbs(implied_post_rate=post, probs=probs)

def kalshi_probs_to_action_buckets(kalshi_probs: Dict[Tuple[str, int], float]) -> Dict[str, float]:
    """
    Converts raw Kalshi classification keys like ("CUT", 50) into labels like "CUT50".
    """
    out: Dict[str, float] = {}
    for (direction, bps), p in kalshi_probs.items():
        if direction == "HOLD":
            out["HOLD"] = float(p)
        elif direction in ("CUT", "HIKE"):
            out[f"{direction}{int(bps)}"] = float(p)
    return out
