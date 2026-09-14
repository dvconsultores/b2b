"""Sync bounces and complaints from the SES suppression list into the contact database (spec 003).

Usage: python -m b2b.sync_bounces [--db data/b2b.sqlite3] [--env .env] [--dry-run]

Bounced addresses are marked bounced and complaints opted out, so they are never emailed again.
Prints counts only.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from b2b import ConfigError, store
from b2b.bounces import apply_suppressions
from b2b.ses_api import SesApiError, list_suppressed, load_aws_settings, make_clients

PROG = "sync_bounces"


def _error(message: str) -> None:
    print(f"{PROG}: error: {message}", file=sys.stderr)


def main(argv: list[str] | None = None, *, clients=None) -> int:
    parser = argparse.ArgumentParser(prog=f"python -m b2b.{PROG}", description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="data/b2b.sqlite3")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--dry-run", action="store_true", help="show the counts without writing")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.is_file():
        _error(f"{db_path}: database not found")
        return 2
    try:
        if clients is None:
            clients = make_clients(load_aws_settings(Path(args.env)))
        suppressed = list_suppressed(clients)
    except ConfigError as exc:
        _error(str(exc))
        return 1
    except SesApiError as exc:
        _error(f"SES API error ({exc})")
        return 1

    try:
        conn = store.connect(db_path)
        try:
            store.ensure_schema(conn)
            result = apply_suppressions(conn, suppressed, dry_run=args.dry_run)
        finally:
            conn.close()
    except (store.SchemaError, sqlite3.Error) as exc:
        _error(f"{db_path}: {exc if isinstance(exc, store.SchemaError) else type(exc).__name__}")
        return 2

    line = (f"{PROG}: suppressed {result.suppressed} | matched {result.matched} | "
            f"newly bounced {result.newly_bounced} | newly opted out {result.newly_opted_out} | "
            f"already marked {result.already_marked} | not in database {result.not_in_database}")
    if args.dry_run:
        line += " | dry run, nothing written"
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
