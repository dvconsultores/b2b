"""Email verification results from an external service (NeverBounce, ZeroBounce) (spec 004).

Only email addresses leave the database (export file); results come back as the service's CSV
and set `contacts.verification`. Status words from the known services are mapped to
valid / catch_all / unknown / invalid.
"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from b2b import InputError, store

# Provider status words → stored status (NeverBounce, ZeroBounce and common synonyms).
STATUS_WORDS = {
    "valid": "valid",
    "deliverable": "valid",
    "catchall": "catch_all",
    "catch-all": "catch_all",
    "catch_all": "catch_all",
    "accept_all": "catch_all",
    "accept-all": "catch_all",
    "unknown": "unknown",
    "risky": "unknown",
    "invalid": "invalid",
    "undeliverable": "invalid",
    "disposable": "invalid",
    "spamtrap": "invalid",
    "abuse": "invalid",
    "do_not_mail": "invalid",
}

EMAIL_HEADERS = ("email", "email address", "e-mail", "emailaddress")
STATUS_HEADERS = ("zb status", "result", "neverbounce result", "email status", "email_status",
                  "verification status", "status")


@dataclass
class ResultRows:
    results: dict[str, str] = field(default_factory=dict)   # email → stored status (last row wins)
    rows: int = 0
    blank_email: int = 0
    unrecognized_status: int = 0


@dataclass
class ApplyResult:
    matched: int = 0
    not_in_database: int = 0
    by_status: dict[str, int] = field(default_factory=lambda: {s: 0 for s in ("valid", "catch_all", "unknown", "invalid")})


def _find_column(headers: list[str], override: str | None, candidates: tuple[str, ...], what: str) -> int:
    normalized = [header.strip().lower() for header in headers]
    if override is not None:
        wanted = override.strip().lower()
        if wanted in normalized:
            return normalized.index(wanted)
        raise InputError(f"{what} column '{override}' not found; columns: {', '.join(headers)}")
    for candidate in candidates:
        if candidate in normalized:
            return normalized.index(candidate)
    raise InputError(f"no {what} column found (use --{what}-column); columns: {', '.join(headers)}")


def read_results(path: Path, *, email_column: str | None = None, status_column: str | None = None) -> ResultRows:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        raise InputError(f"{path}: cannot read file") from None
    except UnicodeDecodeError:
        raise InputError(f"{path}: not a UTF-8 CSV file") from None
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(text.splitlines(), dialect)
    headers = next(reader, None)
    if not headers:
        raise InputError(f"{path}: empty file")
    email_index = _find_column(headers, email_column, EMAIL_HEADERS, "email")
    status_index = _find_column(headers, status_column, STATUS_HEADERS, "status")

    parsed = ResultRows()
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        parsed.rows += 1
        email = row[email_index].strip().lower() if email_index < len(row) else ""
        word = row[status_index].strip().lower() if status_index < len(row) else ""
        if not email:
            parsed.blank_email += 1
            continue
        status = STATUS_WORDS.get(word)
        if status is None:
            parsed.unrecognized_status += 1
            continue
        parsed.results[email] = status
    return parsed


def apply_results(conn: sqlite3.Connection, results: dict[str, str], now: str, *, dry_run: bool = False) -> ApplyResult:
    applied = ApplyResult()
    updates: list[tuple[str, str, str]] = []
    for email, status in results.items():
        if conn.execute("SELECT 1 FROM contacts WHERE email = ?", (email,)).fetchone() is None:
            applied.not_in_database += 1
            continue
        applied.matched += 1
        applied.by_status[status] += 1
        updates.append((status, now, email))
    if updates and not dry_run:
        with store.transaction(conn):
            conn.executemany("UPDATE contacts SET verification = ?, verified_at = ? WHERE email = ?", updates)
    return applied
