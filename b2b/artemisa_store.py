"""Artemisa P2P tracker (spec 006 plan D4): the platform's own users in `data/artemisa.sqlite3`,
with the spec 002 `runs` / `send_attempts` tables so `b2b.tracking` is reused unchanged.
Never stores names beyond `first_name` / `nickname`, phones or the KYC name."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from b2b import store
from b2b.store import SchemaError, transaction

if TYPE_CHECKING:
    from b2b.artemisa_csv import ArtemisaRow

SCHEMA_VERSION = 1

# Columns the import may write on an existing contact (keyed by user_id). Tracking columns are
# never touched by the import.
DESCRIPTIVE_COLUMNS = ("email", "first_name", "nickname", "types")

_CREATE_CONTACTS = """
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE CHECK (user_id > 0),
    email TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    types TEXT NOT NULL DEFAULT '',
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

_SELECT_DESCRIPTIVE = f"SELECT {', '.join(DESCRIPTIVE_COLUMNS)} FROM contacts WHERE user_id = ?"
_INSERT_CONTACT = (
    f"INSERT INTO contacts (user_id, {', '.join(DESCRIPTIVE_COLUMNS)}, created_at, updated_at) "
    f"VALUES ({', '.join('?' for _ in range(len(DESCRIPTIVE_COLUMNS) + 3))})"
)
_UPDATE_DESCRIPTIVE = (
    f"UPDATE contacts SET {', '.join(f'{column} = ?' for column in DESCRIPTIVE_COLUMNS)}, "
    "updated_at = ? WHERE user_id = ?"
)

# Never contacted in this campaign (any attempt status counts), never bounced, never opted out.
_SELECT_RECIPIENTS = """
SELECT c.id, c.email, c.first_name FROM contacts c
WHERE c.bounced = 0 AND c.opted_out = 0
  AND NOT EXISTS (SELECT 1 FROM send_attempts a WHERE a.contact_id = c.id AND a.campaign = ? AND a.step = 1)
ORDER BY c.id
"""


@dataclass
class UpsertResult:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    conflict: int = 0


@dataclass(frozen=True)
class Recipient:
    contact_id: int
    email: str
    first_name: str


def connect(path: Path) -> sqlite3.Connection:
    return store.connect(path)


def _database_file(conn: sqlite3.Connection) -> str:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return row[2]
    return "database"


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the Artemisa tables, or refuse a database that belongs to another tool."""
    if _has_table(conn, "contacts"):
        columns = {row[1] for row in conn.execute("PRAGMA table_info(contacts)")}
        if "user_id" not in columns:
            raise SchemaError(f"{_database_file(conn)}: not an Artemisa database")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise SchemaError(f"{_database_file(conn)}: schema version {version} is newer than this tool ({SCHEMA_VERSION})")
    if version == 0:
        if _has_table(conn, "contacts"):
            raise SchemaError(f"{_database_file(conn)}: contacts table exists without a schema version")
        with transaction(conn):
            conn.execute(_CREATE_CONTACTS)
            conn.execute(store._CREATE_RUNS)
            conn.execute(store._CREATE_SEND_ATTEMPTS)
            for statement in store._V2_INDEXES:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def count_contacts(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]


def upsert_contacts(conn: sqlite3.Connection, rows: Sequence[ArtemisaRow], now: str) -> UpsertResult:
    """Insert new users and refresh descriptive columns of existing ones, keyed by user_id.

    The caller holds the transaction. Tracking columns are never updated. A row whose
    email already belongs to another user_id is a conflict and is skipped.
    """
    result = UpsertResult()
    for row in rows:
        descriptive = tuple(getattr(row, column) for column in DESCRIPTIVE_COLUMNS)
        existing = conn.execute(_SELECT_DESCRIPTIVE, (row.user_id,)).fetchone()
        if existing is not None and tuple(existing) == descriptive:
            result.unchanged += 1
            continue
        owner = conn.execute("SELECT user_id FROM contacts WHERE email = ?", (row.email,)).fetchone()
        if owner is not None and owner[0] != row.user_id:
            result.conflict += 1
            continue
        if existing is None:
            conn.execute(_INSERT_CONTACT, (row.user_id, *descriptive, now, now))
            result.new += 1
        else:
            conn.execute(_UPDATE_DESCRIPTIVE, (*descriptive, now, row.user_id))
            result.updated += 1
    return result


def select_recipients(conn: sqlite3.Connection, campaign: str) -> list[Recipient]:
    return [Recipient(row[0], row[1], row[2]) for row in conn.execute(_SELECT_RECIPIENTS, (campaign,))]


def attempts_in_last_day(conn: sqlite3.Connection, now: datetime) -> tuple[int, str | None]:
    cutoff = (now - timedelta(hours=24)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count, oldest = conn.execute(
        "SELECT COUNT(*), MIN(created_at) FROM send_attempts WHERE created_at > ?", (cutoff,)
    ).fetchone()
    return count, oldest
