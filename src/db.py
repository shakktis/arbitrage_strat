import sqlite3
from typing import Any, Dict

def connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path, check_same_thread=False)

def init(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            ts_utc TEXT NOT NULL,
            source TEXT NOT NULL,
            key TEXT NOT NULL,
            value REAL,
            meta TEXT,
            PRIMARY KEY (ts_utc, source, key)
        )
        """
    )
    conn.commit()

def insert_snapshot(conn: sqlite3.Connection, ts_utc: str, source: str, payload: Dict[str, Any]) -> None:
    cur = conn.cursor()
    for k, v in payload.items():
        cur.execute(
            "INSERT OR REPLACE INTO snapshots (ts_utc, source, key, value, meta) VALUES (?, ?, ?, ?, ?)",
            (ts_utc, source, k, float(v) if v is not None else None, None),
        )
    conn.commit()
