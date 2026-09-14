"""Import email verification results (NeverBounce / ZeroBounce CSV) into the contact database (spec 004).

Usage: python -m b2b.import_verification RESULTS.csv [--db data/b2b.sqlite3]
       [--email-column NAME] [--status-column NAME] [--dry-run]

Sets each matching contact's verification to valid, catch_all, unknown or invalid. Campaigns
send only to the statuses in `allowed_verification` (default: valid). Prints counts only.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from b2b import InputError, store
from b2b.verification import STATUS_WORDS, apply_results, read_results

PROG = "import_verification"


def _error(message: str) -> None:
    print(f"{PROG}: error: {message}", file=sys.stderr)


def main(argv: list[str] | None = None, *, now: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"python -m b2b.{PROG}", description=__doc__.splitlines()[0])
    parser.add_argument("results")
    parser.add_argument("--db", default="data/b2b.sqlite3")
    parser.add_argument("--email-column")
    parser.add_argument("--status-column")
    parser.add_argument("--dry-run", action="store_true", help="show the counts without writing")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.is_file():
        _error(f"{db_path}: database not found")
        return 2
    try:
        parsed = read_results(Path(args.results), email_column=args.email_column, status_column=args.status_column)
    except InputError as exc:
        _error(str(exc))
        return 1
    if parsed.unrecognized_status:
        _error(f"{parsed.unrecognized_status} rows have an unrecognized status; nothing imported "
               f"(known: {', '.join(sorted(STATUS_WORDS))}; check --status-column)")
        return 1

    try:
        conn = store.connect(db_path)
        try:
            store.ensure_schema(conn)
            applied = apply_results(conn, parsed.results, now or store.utc_now(), dry_run=args.dry_run)
        finally:
            conn.close()
    except store.SchemaError as exc:
        _error(str(exc))
        return 2
    except sqlite3.Error as exc:
        _error(f"{db_path}: database error ({type(exc).__name__})")
        return 2

    counts = applied.by_status
    line = (f"{PROG}: rows {parsed.rows} | blank email {parsed.blank_email} | matched {applied.matched} | "
            f"not in database {applied.not_in_database} | valid {counts['valid']} | "
            f"catch_all {counts['catch_all']} | unknown {counts['unknown']} | invalid {counts['invalid']}")
    if args.dry_run:
        line += " | dry run, nothing written"
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
