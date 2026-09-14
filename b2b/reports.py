"""Report entities and counting helpers for reconciliation and totals (plan D13)."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class SourceRef:
    source_file: str = ""
    source_sheet: str = ""
    source_row: int | None = None


@dataclass(frozen=True)
class RejectedRow:
    ref: SourceRef
    email_raw: str
    reason: str


@dataclass(frozen=True)
class ReviewItem:
    type: str
    ref: SourceRef
    detail: str
    count: int = 1


@dataclass
class SourceCounts:
    source_file: str
    source_year: int | None
    sheets_skipped: list[str] = field(default_factory=list)
    rows_read: int = 0
    split_extra: int = 0
    format_rejected: int = 0
    merged: int = 0
    conflicts: int = 0
    new: int = 0
    existing_updated: int = 0
    existing_unchanged: int = 0
    domain_rejected: int = 0
    unverified: int = 0
    personal: int = 0
    generic: int = 0
    missing_city: int = 0
    distinct_companies: int = 0


def reconciles(c: SourceCounts) -> bool:
    return c.rows_read + c.split_extra == (
        c.format_rejected
        + c.merged
        + c.new
        + c.existing_updated
        + c.existing_unchanged
        + c.domain_rejected
        + c.unverified
    )


def total_counts(per_source: Sequence[SourceCounts], distinct_companies: int) -> SourceCounts:
    total = SourceCounts(source_file="total", source_year=None)
    for c in per_source:
        total.sheets_skipped.extend(c.sheets_skipped)
        total.rows_read += c.rows_read
        total.split_extra += c.split_extra
        total.format_rejected += c.format_rejected
        total.merged += c.merged
        total.conflicts += c.conflicts
        total.new += c.new
        total.existing_updated += c.existing_updated
        total.existing_unchanged += c.existing_unchanged
        total.domain_rejected += c.domain_rejected
        total.unverified += c.unverified
        total.personal += c.personal
        total.generic += c.generic
        total.missing_city += c.missing_city
    total.distinct_companies = distinct_companies
    return total


def stage_rejects(reports_dir: Path, rows: Sequence[RejectedRow]) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    staged = reports_dir / ".rejects.csv.tmp"
    with staged.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["source_file", "source_sheet", "source_row", "email_raw", "reason"]
        )
        for row in rows:
            writer.writerow(
                [
                    row.ref.source_file,
                    row.ref.source_sheet,
                    "" if row.ref.source_row is None else row.ref.source_row,
                    row.email_raw,
                    row.reason,
                ]
            )
    return staged


def stage_review(reports_dir: Path, items: Sequence[ReviewItem]) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    staged = reports_dir / ".review.csv.tmp"
    with staged.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["type", "source_file", "source_sheet", "source_row", "detail", "count"]
        )
        for item in sorted(items, key=lambda item: item.type):
            writer.writerow(
                [
                    item.type,
                    item.ref.source_file,
                    item.ref.source_sheet,
                    "" if item.ref.source_row is None else item.ref.source_row,
                    item.detail,
                    item.count,
                ]
            )
    return staged


def publish(staged: Path, final: Path) -> None:
    os.replace(staged, final)


def discard(staged: Path) -> None:
    staged.unlink(missing_ok=True)


def format_summary(per_source: Sequence[SourceCounts], total: SourceCounts, not_in_sources: int,
                   db_path: Path, contacts: int, rejects_path: Path, rejects_rows: int,
                   review_path: Path, review_rows: int) -> str:
    lines = ["import_contacts: done"]

    def block(c: SourceCounts) -> None:
        lines.append("  " + f"{'sheets skipped:':<24}" + (", ".join(c.sheets_skipped) or "-"))
        for label, value in (
            ("rows read", c.rows_read),
            ("extra from split cells", c.split_extra),
            ("rejected (format)", c.format_rejected),
            ("merged duplicates", c.merged),
            ("duplicate conflicts", c.conflicts),
            ("new contacts", c.new),
            ("existing updated", c.existing_updated),
            ("existing unchanged", c.existing_unchanged),
            ("rejected (domain)", c.domain_rejected),
            ("unverified", c.unverified),
            ("personal", c.personal),
            ("generic", c.generic),
            ("missing city", c.missing_city),
            ("distinct companies", c.distinct_companies),
        ):
            lines.append("  " + f"{label + ':':<24}{value:>7}")

    for c in per_source:
        lines.append(f"source: {c.source_file} (year {c.source_year})")
        block(c)

    lines.append("total")
    block(total)
    lines.append("  " + f"{'contacts not in sources:':<24}{not_in_sources:>7}")
    lines.append(f"database: {db_path} ({contacts} contacts)")
    lines.append(
        f"reports:  {rejects_path} ({rejects_rows} rows), {review_path} ({review_rows} rows)"
    )
    return "\n".join(lines) + "\n"
