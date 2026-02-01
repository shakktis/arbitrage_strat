# src/effr_client.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import csv
import io
import time
import requests

FRED_EFFR_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=EFFR"

@dataclass(frozen=True)
class EffrPoint:
    obs_date: date
    rate: float  # percent, e.g. 5.33

def _parse_latest_effr_from_csv_text(text: str) -> EffrPoint:
    text = (text or "").strip()
    if not text:
        raise RuntimeError("Empty CSV content.")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        raise RuntimeError("Unexpected CSV format (too few rows).")

    # Find last non-missing EFFR (FRED uses '.' sometimes)
    for row in reversed(rows[1:]):
        if len(row) < 2:
            continue
        d, v = row[0].strip(), row[1].strip()
        if not d or not v or v == ".":
            continue
        y, m, dd = map(int, d.split("-"))
        return EffrPoint(obs_date=date(y, m, dd), rate=float(v))

    raise RuntimeError("No valid EFFR value found in CSV.")

def fetch_latest_effr(timeout: int = 8, retries: int = 2) -> EffrPoint:
    """
    Fast method:
      - Try HTTP Range request to only download the last chunk of the CSV
      - Parse the latest non-missing observation from that chunk
    Fallback:
      - Download full CSV if Range not supported
    """
    headers = {"User-Agent": "Mozilla/5.0"}

    last_err = None
    for attempt in range(retries + 1):
        try:
            # 1) Try fetching only the tail (last ~32KB)
            h = dict(headers)
            h["Range"] = "bytes=-32768"
            r = requests.get(FRED_EFFR_CSV, headers=h, timeout=timeout)

            # If server supports Range, status is often 206
            if r.status_code in (200, 206):
                try:
                    return _parse_latest_effr_from_csv_text(r.text)
                except Exception:
                    # If the tail chunk didn't contain header/rows cleanly, fall back to full fetch below
                    pass

            # 2) Full fetch fallback
            r2 = requests.get(FRED_EFFR_CSV, headers=headers, timeout=timeout)
            r2.raise_for_status()
            return _parse_latest_effr_from_csv_text(r2.text)

        except Exception as e:
            last_err = e
            # small backoff then retry
            time.sleep(0.5 * (attempt + 1))

    raise RuntimeError(f"EFFR fetch failed after retries: {last_err}")

