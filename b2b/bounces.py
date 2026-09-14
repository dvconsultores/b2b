"""Apply the SES suppression list to contacts: bounces → bounced, complaints → opted out (spec 003).

Tracking fields only ever go from 0 to 1; nothing is un-marked or deleted.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timezone
from typing import Sequence

from b2b import store
from b2b.ses_api import Suppressed


@dataclass
class SyncResult:
    suppressed: int = 0
    matched: int = 0
    newly_bounced: int = 0
    newly_opted_out: int = 0
    already_marked: int = 0
    not_in_database: int = 0
    ignored: int = 0


def apply_suppressions(conn: sqlite3.Connection, suppressed: Sequence[Suppressed], *,
                       dry_run: bool = False) -> SyncResult:
    result = SyncResult(suppressed=len(suppressed))
    updates: list[tuple[str, tuple]] = []
    for entry in suppressed:
        row = conn.execute("SELECT id, bounced, opted_out FROM contacts WHERE email = ?", (entry.email,)).fetchone()
        if row is None:
            result.not_in_database += 1
            continue
        result.matched += 1
        contact_id, bounced, opted_out = row[0], row[1], row[2]
        stamp = entry.updated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if entry.reason == "BOUNCE":
            if bounced:
                result.already_marked += 1
            else:
                updates.append(("UPDATE contacts SET bounced = 1, bounced_at = ? WHERE id = ? AND bounced = 0",
                                (stamp, contact_id)))
                result.newly_bounced += 1
        elif entry.reason == "COMPLAINT":
            if opted_out:
                result.already_marked += 1
            else:
                updates.append(("UPDATE contacts SET opted_out = 1, opted_out_at = ? WHERE id = ? AND opted_out = 0",
                                (stamp, contact_id)))
                result.newly_opted_out += 1
        else:
            result.ignored += 1
    if updates and not dry_run:
        with store.transaction(conn):
            for sql, params in updates:
                conn.execute(sql, params)
    return result
