"""Record a manual inbox check, releasing the batch hold for the next production batch.

Usage: python -m b2b.mark_inbox_checked [--db data/b2b.sqlite3]

Until inbox processing is automated, the operator reviews bounces, replies and opt-outs by hand,
updates contacts if needed, and then runs this command. It writes one `runs` row with
kind 'inbox' (spec 002 FR-018). Prints the timestamp only.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from b2b import store

PROG = "mark_inbox_checked"


def main(argv: list[str] | None = None, *, now: Callable[[], datetime] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"python -m b2b.{PROG}", description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="data/b2b.sqlite3")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"{PROG}: error: {db_path}: database not found", file=sys.stderr)
        return 2
    moment = (now or (lambda: datetime.now(timezone.utc)))()
    stamp = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        conn = store.connect(db_path)
        try:
            store.ensure_schema(conn)
            with store.transaction(conn):
                conn.execute(
                    "INSERT INTO runs (kind, started_at, finished_at, stop_reason) "
                    "VALUES ('inbox', ?, ?, 'manual_check')",
                    (stamp, stamp),
                )
        finally:
            conn.close()
    except (store.SchemaError, sqlite3.Error) as exc:
        print(f"{PROG}: error: {db_path}: {exc if isinstance(exc, store.SchemaError) else type(exc).__name__}",
              file=sys.stderr)
        return 2
    print(f"{PROG}: recorded manual inbox check at {stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
