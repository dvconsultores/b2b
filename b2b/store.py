"""SQLite contact store: schema v1 contacts, v2 send tracking, v3 email verification, and an
upsert that never touches tracking fields (spec 001 plan D10, spec 002 plan D3, spec 004 plan D1)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

SCHEMA_VERSION = 3

VERIFICATION_STATUSES = ("unverified", "valid", "catch_all", "unknown", "invalid")

# Columns the import may write on an existing contact. Tracking columns and created_at are
# deliberately absent: only specs 002 and 003 change them.
DESCRIPTIVE_COLUMNS = (
    "company",
    "company_key",
    "contact_name",
    "city",
    "tax_id",
    "area",
    "classification",
    "source_file",
    "source_sheet",
    "source_row",
    "source_year",
)

_CREATE_CONTACTS = """
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    company TEXT NOT NULL DEFAULT '',
    company_key TEXT NOT NULL,
    contact_name TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    tax_id TEXT NOT NULL DEFAULT '',
    area TEXT NOT NULL DEFAULT '',
    classification TEXT NOT NULL CHECK (classification IN ('personal', 'generic')),
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL CHECK (source_row > 0),
    source_year INTEGER NOT NULL CHECK (source_year IN (2009, 2020)),
    times_contacted INTEGER NOT NULL DEFAULT 0 CHECK (times_contacted >= 0),
    last_contacted_at TEXT,
    bounced INTEGER NOT NULL DEFAULT 0 CHECK (bounced IN (0, 1)),
    bounced_at TEXT,
    responded INTEGER NOT NULL DEFAULT 0 CHECK (responded IN (0, 1)),
    responded_at TEXT,
    opted_out INTEGER NOT NULL DEFAULT 0 CHECK (opted_out IN (0, 1)),
    opted_out_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((times_contacted = 0) = (last_contacted_at IS NULL)),
    CHECK ((bounced = 0) = (bounced_at IS NULL)),
    CHECK ((responded = 0) = (responded_at IS NULL)),
    CHECK ((opted_out = 0) = (opted_out_at IS NULL))
)
"""

_CREATE_COMPANY_KEY_INDEX = "CREATE INDEX idx_contacts_company_key ON contacts(company_key)"

_CREATE_RUNS = """
CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('send_production', 'inbox')),
    campaign TEXT,
    step INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stop_reason TEXT,
    forced_no_dmarc INTEGER NOT NULL DEFAULT 0 CHECK (forced_no_dmarc IN (0, 1))
)
"""

_CREATE_SEND_ATTEMPTS = """
CREATE TABLE send_attempts (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    campaign TEXT NOT NULL,
    step INTEGER NOT NULL CHECK (step = 1),
    status TEXT NOT NULL CHECK (status IN
        ('pending', 'accepted', 'permanent_rejection', 'temporary_failure', 'unknown')),
    error_kind TEXT,
    smtp_code INTEGER,
    message_id TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (contact_id, campaign, step),
    CHECK ((status = 'pending') = (finished_at IS NULL)),
    CHECK ((status = 'accepted') = (message_id IS NOT NULL))
)
"""

_V2_INDEXES = (
    "CREATE INDEX idx_runs_kind_started ON runs(kind, started_at)",
    "CREATE INDEX idx_attempts_created ON send_attempts(created_at)",
    "CREATE INDEX idx_attempts_campaign ON send_attempts(campaign, step, status)",
)

_SELECT_DESCRIPTIVE = f"SELECT {', '.join(DESCRIPTIVE_COLUMNS)} FROM contacts WHERE email = ?"

_INSERT_CONTACT = (
    f"INSERT INTO contacts (email, {', '.join(DESCRIPTIVE_COLUMNS)}, created_at, updated_at) "
    f"VALUES ({', '.join('?' for _ in range(len(DESCRIPTIVE_COLUMNS) + 3))})"
)

_UPDATE_DESCRIPTIVE = (
    f"UPDATE contacts SET {', '.join(f'{column} = ?' for column in DESCRIPTIVE_COLUMNS)}, "
    "updated_at = ? WHERE email = ?"
)


class SchemaError(Exception):
    """The database schema is not one this tool can use."""


@dataclass(frozen=True)
class ContactValues:
    email: str
    company: str
    company_key: str
    contact_name: str
    city: str
    tax_id: str
    area: str
    classification: str
    source_file: str
    source_sheet: str
    source_row: int
    source_year: int


@dataclass
class UpsertResult:
    new: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _database_file(conn: sqlite3.Connection) -> str:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return row[2]
    return "database"


def _migrate_1_to_2(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute(_CREATE_RUNS)
        conn.execute(_CREATE_SEND_ATTEMPTS)
        for statement in _V2_INDEXES:
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 2")


def _migrate_2_to_3(conn: sqlite3.Connection) -> None:
    statuses = ", ".join(f"'{status}'" for status in VERIFICATION_STATUSES)
    with transaction(conn):
        conn.execute(
            "ALTER TABLE contacts ADD COLUMN verification TEXT NOT NULL DEFAULT 'unverified' "
            f"CHECK (verification IN ({statuses}))"
        )
        conn.execute("ALTER TABLE contacts ADD COLUMN verified_at TEXT")
        conn.execute("PRAGMA user_version = 3")


def ensure_schema(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise SchemaError(
            f"{_database_file(conn)}: schema version {version} is newer than this tool "
            f"({SCHEMA_VERSION})"
        )
    if version == 0:
        has_contacts = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'contacts'"
        ).fetchone()
        if has_contacts:
            raise SchemaError(
                f"{_database_file(conn)}: contacts table exists without a schema version"
            )
        with transaction(conn):
            conn.execute(_CREATE_CONTACTS)
            conn.execute(_CREATE_COMPANY_KEY_INDEX)
            conn.execute("PRAGMA user_version = 1")
        version = 1
    if version == 1:
        _migrate_1_to_2(conn)
        version = 2
    if version == 2:
        _migrate_2_to_3(conn)


def existing_emails(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT email FROM contacts")}


def count_contacts(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]


def upsert_contacts(
    conn: sqlite3.Connection, values: Sequence[ContactValues], now: str
) -> UpsertResult:
    """Insert new contacts and refresh descriptive columns of existing ones.

    The caller holds the transaction. Tracking columns and created_at are never updated.
    """
    result = UpsertResult()
    for value in values:
        descriptive = tuple(getattr(value, column) for column in DESCRIPTIVE_COLUMNS)
        row = conn.execute(_SELECT_DESCRIPTIVE, (value.email,)).fetchone()
        if row is None:
            conn.execute(_INSERT_CONTACT, (value.email, *descriptive, now, now))
            result.new.append(value.email)
        elif tuple(row) != descriptive:
            conn.execute(_UPDATE_DESCRIPTIVE, (*descriptive, now, value.email))
            result.updated.append(value.email)
        else:
            result.unchanged.append(value.email)
    return result
