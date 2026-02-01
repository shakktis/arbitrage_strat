# src/link_parser.py
from __future__ import annotations

import re
from typing import Tuple
from urllib.parse import urlparse

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

def extract_kalshi_event_slug(url: str) -> str:
    """
    Accepts either:
      - https://kalshi.com/markets/kxfeddecision/fed-meeting/kxfeddecision-26jan
      - kxfeddecision-26jan
      - KXFEDDECISION-26JAN
    Returns the slug like: kxfeddecision-26jan
    """
    s = (url or "").strip()
    if not s:
        raise ValueError("Empty Kalshi link.")

    # If they paste a full URL, take the last path segment
    if "://" in s:
        p = urlparse(s)
        parts = [x for x in p.path.split("/") if x]
        if not parts:
            raise ValueError("Could not parse Kalshi URL path.")
        slug = parts[-1]
    else:
        slug = s

    slug = slug.strip().lower()

    # Normalize if they pasted ticker format
    slug = slug.replace("kxfeddecision-", "kxfeddecision-")
    slug = slug.replace("kxfed-", "kxfed-")
    slug = slug.replace("_", "-")

    # Basic sanity check: must contain a dash and end with yy+mon like 26jan
    if not re.search(r"-\d{2}[a-z]{3}$", slug):
        # allow other formats, but this is the expected one for your use-case
        raise ValueError("Kalshi link slug not in expected format like kxfeddecision-26jan.")
    return slug

def slug_to_year_month(slug: str) -> Tuple[int, int]:
    """
    slug ends with: -26jan -> (2026, 1)
    """
    m = re.search(r"-(\d{2})([a-z]{3})$", slug.lower())
    if not m:
        raise ValueError("Could not parse year/month from slug.")
    yy = int(m.group(1))
    mon = m.group(2)
    if mon not in _MONTHS:
        raise ValueError(f"Unknown month code in slug: {mon}")
    year = 2000 + yy
    month = _MONTHS[mon]
    return year, month

def slug_to_event_ticker(slug: str) -> str:
    """
    kxfeddecision-26jan -> KXFEDDECISION-26JAN
    """
    return slug.upper()
