#!/usr/bin/env python3
"""Delete access_events older than N days from an RWA SQLite DB.

Usage:
  prune-access-events.py /path/to/rwa.db [--days 90]
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    db = Path(args.db)
    if not db.is_file():
        print(f"skip prune: db missing ({db})")
        return 0
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max(1, args.days))
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='access_events'"
        ).fetchone()
        if not row:
            print("skip prune: access_events table missing")
            return 0
        cur = conn.execute("DELETE FROM access_events WHERE created_at < ?", (cutoff,))
        conn.commit()
        deleted = cur.rowcount if cur.rowcount is not None else 0
        # Reclaim space occasionally when many rows dropped.
        if deleted >= 1000:
            conn.execute("VACUUM")
        print(f"pruned {deleted} access_events older than {args.days}d (before {cutoff})")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
