from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple
import requests
from bs4 import BeautifulSoup

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

_MONTHS = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]
_MONTH_TO_NUM = {m: i+1 for i, m in enumerate(_MONTHS)}

@dataclass(frozen=True)
class FomcMeeting:
    year: int
    month: int
    start_day: int
    end_day: int

    @property
    def start_date(self) -> date:
        return date(self.year, self.month, self.start_day)

    @property
    def end_date(self) -> date:
        return date(self.year, self.month, self.end_day)

def _fetch_text(url: str = FOMC_URL) -> str:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    # Pull text with line breaks so regex parsing works
    return soup.get_text("\n")

def _extract_year_block(text: str, year: int) -> str:
    # Grab chunk between "#### 2026 FOMC Meetings" and "#### 2027 FOMC Meetings" etc.
    # The page contains "2026 FOMC Meetings" and "2027 FOMC Meetings" in the text. :contentReference[oaicite:2]{index=2}
    start_pat = rf"{year}\s+FOMC\s+Meetings"
    end_pat = rf"{year+1}\s+FOMC\s+Meetings"
    m1 = re.search(start_pat, text)
    if not m1:
        return ""
    start = m1.start()
    m2 = re.search(end_pat, text[start:])
    end = start + m2.start() if m2 else len(text)
    return text[start:end]

def _parse_meetings_from_block(block: str, year: int) -> List[FomcMeeting]:
    meetings: List[FomcMeeting] = []
    # Matches: "January\n27-28" etc (sometimes with asterisks nearby)
    # Official schedule includes patterns like "January 27-28" for 2026. :contentReference[oaicite:3]{index=3}
    pat = re.compile(
        r"(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\s*-\s*(\d{1,2})",
        re.IGNORECASE
    )
    for month_name, d1, d2 in pat.findall(block):
        month = _MONTH_TO_NUM[month_name[0].upper() + month_name[1:].lower()]
        meetings.append(FomcMeeting(year=year, month=month, start_day=int(d1), end_day=int(d2)))
    return meetings

def get_upcoming_meeting(today: Optional[date] = None) -> FomcMeeting:
    if today is None:
        today = date.today()

    text = _fetch_text()

    # Parse current year + next year to be safe around year boundaries
    years = [today.year, today.year + 1]
    all_meetings: List[FomcMeeting] = []
    for y in years:
        block = _extract_year_block(text, y)
        all_meetings.extend(_parse_meetings_from_block(block, y))

    # Pick next meeting whose end_date is >= today
    all_meetings.sort(key=lambda m: m.end_date)
    for m in all_meetings:
        if m.end_date >= today:
            return m

    raise RuntimeError("Could not find an upcoming FOMC meeting from the Fed calendar.")
