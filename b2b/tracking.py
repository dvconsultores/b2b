"""Send runs and attempts: at-most-once recording, recovery, bounce rate, batch hold and the
single production-run lock (spec 002 plan D10, D11, data-model.md)."""
from __future__ import annotations

import fcntl
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from b2b import store

if TYPE_CHECKING:
    from b2b.mailer import SendOutcome

_FINAL_STATUSES = ("accepted", "permanent_rejection", "temporary_failure", "unknown")


class SendLockBusy(Exception):
    """Another production send run holds the lock."""


@contextmanager
def send_lock(db_path: Path) -> Iterator[None]:
    lock_path = Path(f"{db_path}.send.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SendLockBusy(str(lock_path)) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def recover_pending(conn: sqlite3.Connection, now: str) -> int:
    """Attempts left pending by a crashed run may have been delivered: mark them unknown."""
    with store.transaction(conn):
        cursor = conn.execute(
            "UPDATE send_attempts SET status = 'unknown', error_kind = 'interrupted', finished_at = ? "
            "WHERE status = 'pending'",
            (now,),
        )
    return cursor.rowcount


def batch_hold_satisfied(conn: sqlite3.Connection) -> bool:
    latest = conn.execute(
        "SELECT COALESCE(finished_at, started_at) FROM runs WHERE kind = 'send_production' "
        "ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return True
    inbox_after = conn.execute(
        "SELECT 1 FROM runs WHERE kind = 'inbox' AND finished_at IS NOT NULL AND finished_at > ? LIMIT 1",
        (latest[0],),
    ).fetchone()
    return inbox_after is not None


def start_run(conn: sqlite3.Connection, campaign: str, step: int, forced_no_dmarc: bool, now: str) -> int:
    with store.transaction(conn):
        cursor = conn.execute(
            "INSERT INTO runs (kind, campaign, step, started_at, forced_no_dmarc) "
            "VALUES ('send_production', ?, ?, ?, ?)",
            (campaign, step, now, int(forced_no_dmarc)),
        )
    return cursor.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, stop_reason: str, now: str) -> None:
    with store.transaction(conn):
        conn.execute("UPDATE runs SET finished_at = ?, stop_reason = ? WHERE id = ?", (now, stop_reason, run_id))


def record_pending(conn: sqlite3.Connection, run_id: int, contact_id: int, campaign: str, step: int,
                   now: str) -> int:
    """Commit the attempt before any SMTP call so a crash can never cause a second send."""
    with store.transaction(conn):
        cursor = conn.execute(
            "INSERT INTO send_attempts (run_id, contact_id, campaign, step, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (run_id, contact_id, campaign, step, now),
        )
    return cursor.lastrowid


def record_outcome(conn: sqlite3.Connection, attempt_id: int, contact_id: int, outcome: SendOutcome,
                   now: str) -> None:
    if outcome.status not in _FINAL_STATUSES:
        raise ValueError(f"not a final attempt status: {outcome.status}")
    with store.transaction(conn):
        cursor = conn.execute(
            "UPDATE send_attempts SET status = ?, error_kind = ?, smtp_code = ?, message_id = ?, finished_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (outcome.status, outcome.error_kind, outcome.smtp_code,
             outcome.message_id if outcome.status == "accepted" else None, now, attempt_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"attempt {attempt_id} is not pending")
        if outcome.status == "accepted":
            conn.execute(
                "UPDATE contacts SET times_contacted = times_contacted + 1, last_contacted_at = ? WHERE id = ?",
                (now, contact_id),
            )
        elif outcome.status == "permanent_rejection":
            conn.execute(
                "UPDATE contacts SET bounced = 1, bounced_at = ? WHERE id = ? AND bounced = 0",
                (now, contact_id),
            )


def attempts_in_last_hour(conn: sqlite3.Connection, now: datetime) -> tuple[int, str | None]:
    cutoff = (now - timedelta(seconds=3600)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count, oldest = conn.execute(
        "SELECT COUNT(*), MIN(created_at) FROM send_attempts WHERE created_at > ?", (cutoff,)
    ).fetchone()
    return count, oldest


def campaign_bounce(conn: sqlite3.Connection, campaign: str, step: int) -> tuple[int, int]:
    bounced, base = conn.execute(
        "SELECT COALESCE(SUM(c.bounced), 0), COUNT(*) FROM send_attempts a "
        "JOIN contacts c ON c.id = a.contact_id "
        "WHERE a.campaign = ? AND a.step = ? AND a.status IN ('accepted', 'permanent_rejection')",
        (campaign, step),
    ).fetchone()
    return bounced, base


def bounce_exceeded(bounced: int, base: int, threshold: float, min_sends: int) -> bool:
    return base >= min_sends and bounced / base > threshold
