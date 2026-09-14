"""Export the email addresses to verify with an external service (spec 004).

Usage: python -m b2b.export_verification [--db data/b2b.sqlite3] [--out-dir data/verification]

Writes one column (`email`) for contacts that could still receive a first email and were never
verified. No names, companies or other fields. The file is created with owner-only permissions.
Prints counts only.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from b2b import store
from b2b.eligibility import verification_candidates

PROG = "export_verification"


def _error(message: str) -> None:
    print(f"{PROG}: error: {message}", file=sys.stderr)


def main(argv: list[str] | None = None, *, now=None) -> int:
    parser = argparse.ArgumentParser(prog=f"python -m b2b.{PROG}", description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="data/b2b.sqlite3")
    parser.add_argument("--out-dir", default="data/verification")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.is_file():
        _error(f"{db_path}: database not found")
        return 2
    try:
        conn = store.connect(db_path)
        try:
            store.ensure_schema(conn)
            emails = verification_candidates(conn)
            already = conn.execute("SELECT COUNT(*) FROM contacts WHERE verification != 'unverified'").fetchone()[0]
        finally:
            conn.close()
    except store.SchemaError as exc:
        _error(str(exc))
        return 2
    except sqlite3.Error as exc:
        _error(f"{db_path}: database error ({type(exc).__name__})")
        return 2

    if not emails:
        print(f"{PROG}: nothing to export (already verified: {already})")
        return 0

    moment = (now or (lambda: datetime.now(timezone.utc)))()
    out_dir = Path(args.out_dir)
    out_path = out_dir / f"verify-emails-{moment:%Y%m%d-%H%M%S}.csv"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(out_dir, 0o700)
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _error(f"{out_path}: already exists")
        return 1
    except OSError:
        _error(f"{out_dir}: cannot write")
        return 1
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        handle.write("email\n")
        handle.writelines(f"{email}\n" for email in emails)

    print(f"{PROG}: exported {len(emails)} addresses to {out_path} (already verified: {already})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
