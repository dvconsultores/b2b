"""Read the Artemisa users export (spec 006 plan D5): only the five columns the campaign needs are
kept (data minimization); invalid rows are counted, never printed."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from b2b import InputError
from b2b.emails import normalize_token, validate

REQUIRED_HEADERS = ("user_id", "email", "first_name", "nickname", "types")
REJECT_REASONS = ("invalid_user_id", "invalid_email", "duplicate_user_id", "duplicate_email")


@dataclass(frozen=True)
class ArtemisaRow:
    user_id: int
    email: str
    first_name: str
    nickname: str
    types: str


@dataclass
class CsvResult:
    rows: list[ArtemisaRow] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=lambda: {reason: 0 for reason in REJECT_REASONS})


def read_artemisa_csv(path: Path) -> CsvResult:
    path = Path(path)
    result = CsvResult()
    seen_ids: set[int] = set()
    seen_emails: set[str] = set()
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        for header in REQUIRED_HEADERS:
            if header not in headers:
                raise InputError(f"{path}: missing header '{header}'")
        for record in reader:
            try:
                user_id = int((record.get("user_id") or "").strip())
            except ValueError:
                user_id = 0
            if user_id <= 0:
                result.rejected["invalid_user_id"] += 1
                continue
            email = normalize_token(record.get("email") or "")
            if validate(email) is not None:
                result.rejected["invalid_email"] += 1
                continue
            if user_id in seen_ids:
                result.rejected["duplicate_user_id"] += 1
                continue
            if email in seen_emails:
                result.rejected["duplicate_email"] += 1
                continue
            seen_ids.add(user_id)
            seen_emails.add(email)
            result.rows.append(ArtemisaRow(
                user_id=user_id,
                email=email,
                first_name=(record.get("first_name") or "").strip(),
                nickname=(record.get("nickname") or "").strip(),
                types=(record.get("types") or "").strip(),
            ))
    return result
