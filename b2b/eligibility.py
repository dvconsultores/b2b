"""Select first-email recipients: one eligible, verified personal contact per company
(spec 002 plan D8, spec 004 plan D3)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Recipient:
    contact_id: int
    email: str
    company: str
    company_key: str
    contact_name: str
    city: str
    source_year: int


@dataclass(frozen=True)
class Selection:
    recipients: list[Recipient]
    eligible: int
    skipped_same_company: int
    skipped_not_verified: int = 0


# A contact is a candidate when it was never contacted, never bounced, responded or opted out,
# is personal, has no attempt in this campaign step, and has no unresolved (pending/unknown)
# attempt anywhere. A company is excluded once any of its contacts was (or may have been)
# emailed at this step in any campaign, so a company never receives the same first email twice.
_CANDIDATES = """
SELECT c.id, c.email, c.company, c.company_key, c.contact_name, c.city, c.tax_id, c.area,
       c.source_year, c.source_row, c.verification
FROM contacts c
WHERE c.times_contacted = 0
  AND c.bounced = 0
  AND c.responded = 0
  AND c.opted_out = 0
  AND c.classification = 'personal'
  AND NOT EXISTS (
      SELECT 1 FROM send_attempts a
      WHERE a.contact_id = c.id
        AND ((a.campaign = :campaign AND a.step = :step) OR a.status IN ('pending', 'unknown'))
  )
  AND NOT EXISTS (
      SELECT 1 FROM send_attempts a JOIN contacts other ON other.id = a.contact_id
      WHERE a.step = :step
        AND a.status IN ('accepted', 'pending', 'unknown')
        AND other.company_key = c.company_key
  )
ORDER BY c.id
"""


def select_recipients(conn: sqlite3.Connection, campaign: str, step: int,
                      allowed_verification: Sequence[str] = ("valid",)) -> Selection:
    rows = conn.execute(_CANDIDATES, {"campaign": campaign, "step": step}).fetchall()
    allowed = set(allowed_verification)
    verified = [row for row in rows if row["verification"] in allowed]

    best_by_company: dict[str, tuple] = {}
    for row in verified:
        (contact_id, email, company, company_key, contact_name, city, tax_id, area,
         source_year, source_row, _verification) = tuple(row)
        completeness = sum(1 for value in (company, contact_name, city, tax_id, area) if value)
        rank = (-completeness, -source_year, source_row, email)
        current = best_by_company.get(company_key)
        if current is None or rank < current[0]:
            recipient = Recipient(contact_id, email, company, company_key, contact_name, city, source_year)
            best_by_company[company_key] = (rank, recipient)

    chosen = sorted(
        (recipient for _, recipient in best_by_company.values()),
        key=lambda r: (-r.source_year, r.contact_id),
    )
    return Selection(
        recipients=chosen,
        eligible=len(verified),
        skipped_same_company=len(verified) - len(chosen),
        skipped_not_verified=len(rows) - len(verified),
    )


def verification_candidates(conn: sqlite3.Connection, step: int = 1) -> list[str]:
    """Emails worth verifying: would be eligible for a new first-email campaign and were never verified."""
    rows = conn.execute(_CANDIDATES, {"campaign": "", "step": step}).fetchall()
    return [row["email"] for row in rows if row["verification"] == "unverified"]
