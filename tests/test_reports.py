"""Tests for report entities and counting helpers (T008)."""
from __future__ import annotations

import csv

from b2b.reports import (
    RejectedRow,
    ReviewItem,
    SourceCounts,
    SourceRef,
    discard,
    format_summary,
    publish,
    reconciles,
    stage_rejects,
    stage_review,
    total_counts,
)


def test_reconciles_true():
    c = SourceCounts(
        source_file="a.xlsx",
        source_year=2024,
        rows_read=10,
        split_extra=2,
        format_rejected=1,
        merged=1,
        new=5,
        existing_updated=2,
        existing_unchanged=1,
        domain_rejected=1,
        unverified=1,
    )
    assert reconciles(c) is True


def test_reconciles_false():
    c = SourceCounts(
        source_file="a.xlsx",
        source_year=2024,
        rows_read=10,
        split_extra=2,
        format_rejected=1,
        merged=1,
        new=5,
        existing_updated=2,
        existing_unchanged=1,
        domain_rejected=1,
        unverified=0,
    )
    assert reconciles(c) is False


def test_total_counts_sums_and_concatenates():
    a = SourceCounts(
        source_file="a.xlsx",
        source_year=2023,
        sheets_skipped=["s1", "s2"],
        rows_read=10,
        split_extra=2,
        format_rejected=1,
        merged=1,
        conflicts=3,
        new=5,
        existing_updated=2,
        existing_unchanged=1,
        domain_rejected=1,
        unverified=1,
        personal=4,
        generic=6,
        missing_city=2,
        distinct_companies=7,
    )
    b = SourceCounts(
        source_file="b.xlsx",
        source_year=2024,
        sheets_skipped=["s3"],
        rows_read=20,
        split_extra=1,
        format_rejected=2,
        merged=2,
        conflicts=1,
        new=8,
        existing_updated=3,
        existing_unchanged=2,
        domain_rejected=2,
        unverified=2,
        personal=1,
        generic=2,
        missing_city=3,
        distinct_companies=9,
    )
    total = total_counts([a, b], distinct_companies=42)
    assert total.source_file == "total"
    assert total.source_year is None
    assert total.sheets_skipped == ["s1", "s2", "s3"]
    assert total.rows_read == 30
    assert total.split_extra == 3
    assert total.format_rejected == 3
    assert total.merged == 3
    assert total.conflicts == 4
    assert total.new == 13
    assert total.existing_updated == 5
    assert total.existing_unchanged == 3
    assert total.domain_rejected == 3
    assert total.unverified == 3
    assert total.personal == 5
    assert total.generic == 8
    assert total.missing_city == 5
    assert total.distinct_companies == 42


def test_total_counts_empty():
    total = total_counts([], distinct_companies=0)
    assert total.source_file == "total"
    assert total.source_year is None
    assert total.sheets_skipped == []
    assert total.rows_read == 0
    assert total.distinct_companies == 0


def test_stage_rejects_creates_dir_bom_and_header(tmp_path):
    reports_dir = tmp_path / "reports"
    staged = stage_rejects(reports_dir, [])
    assert reports_dir.is_dir()
    assert staged == reports_dir / ".rejects.csv.tmp"
    raw = staged.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with staged.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == [
        "source_file",
        "source_sheet",
        "source_row",
        "email_raw",
        "reason",
    ]


def test_stage_rejects_rows_order_and_none_row(tmp_path):
    rows = [
        RejectedRow(
            ref=SourceRef(source_file="a.xlsx", source_sheet="Hoja1", source_row=2),
            email_raw="bad@@example.com",
            reason="invalid_format",
        ),
        RejectedRow(
            ref=SourceRef(source_file="a.xlsx", source_sheet="Hoja1", source_row=None),
            email_raw="",
            reason="empty",
        ),
    ]
    staged = stage_rejects(tmp_path / "reports", rows)
    with staged.open("r", encoding="utf-8-sig", newline="") as fh:
        data = list(csv.reader(fh))
    assert data[1] == ["a.xlsx", "Hoja1", "2", "bad@@example.com", "invalid_format"]
    assert data[2] == ["a.xlsx", "Hoja1", "", "", "empty"]


def test_stage_rejects_accents_round_trip(tmp_path):
    rows = [
        RejectedRow(
            ref=SourceRef(source_file="contactos.xlsx", source_sheet="Mérida", source_row=3),
            email_raw="josé@example.com",
            reason="domain_not_found",
        )
    ]
    staged = stage_rejects(tmp_path / "reports", rows)
    with staged.open("r", encoding="utf-8-sig", newline="") as fh:
        data = list(csv.reader(fh))
    assert data[1][1] == "Mérida"
    assert data[1][3] == "josé@example.com"


def test_stage_review_creates_dir_bom_and_header(tmp_path):
    reports_dir = tmp_path / "reports"
    staged = stage_review(reports_dir, [])
    assert reports_dir.is_dir()
    assert staged == reports_dir / ".review.csv.tmp"
    raw = staged.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with staged.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == [
        "type",
        "source_file",
        "source_sheet",
        "source_row",
        "detail",
        "count",
    ]


def test_stage_review_stable_sort_by_type(tmp_path):
    items = [
        ReviewItem(type="generic", ref=SourceRef(source_file="a.xlsx"), detail="info@example.com"),
        ReviewItem(type="conflict", ref=SourceRef(source_file="a.xlsx"), detail="x@example.com"),
        ReviewItem(type="generic", ref=SourceRef(source_file="b.xlsx"), detail="sales@example.com"),
        ReviewItem(type="conflict", ref=SourceRef(source_file="b.xlsx"), detail="y@example.com"),
    ]
    staged = stage_review(tmp_path / "reports", items)
    with staged.open("r", encoding="utf-8-sig", newline="") as fh:
        data = list(csv.reader(fh))
    assert [r[0] for r in data[1:]] == ["conflict", "conflict", "generic", "generic"]
    assert [r[4] for r in data[1:]] == [
        "x@example.com",
        "y@example.com",
        "info@example.com",
        "sales@example.com",
    ]


def test_stage_review_accents_and_none_row(tmp_path):
    items = [
        ReviewItem(
            type="missing_city",
            ref=SourceRef(source_file="contactos.xlsx", source_sheet="Mérida", source_row=None),
            detail="Mérida",
            count=3,
        )
    ]
    staged = stage_review(tmp_path / "reports", items)
    with staged.open("r", encoding="utf-8-sig", newline="") as fh:
        data = list(csv.reader(fh))
    assert data[1] == ["missing_city", "contactos.xlsx", "Mérida", "", "Mérida", "3"]


def test_publish_replaces_existing_file(tmp_path):
    staged = tmp_path / ".rejects.csv.tmp"
    staged.write_text("new", encoding="utf-8")
    final = tmp_path / "rejects.csv"
    final.write_text("old", encoding="utf-8")
    publish(staged, final)
    assert final.read_text(encoding="utf-8") == "new"
    assert not staged.exists()


def test_publish_creates_final_when_missing(tmp_path):
    staged = tmp_path / ".review.csv.tmp"
    staged.write_text("data", encoding="utf-8")
    final = tmp_path / "review.csv"
    publish(staged, final)
    assert final.read_text(encoding="utf-8") == "data"


def test_discard_removes_existing_file(tmp_path):
    staged = tmp_path / ".rejects.csv.tmp"
    staged.write_text("x", encoding="utf-8")
    discard(staged)
    assert not staged.exists()


def test_discard_tolerates_missing_file(tmp_path):
    discard(tmp_path / ".rejects.csv.tmp")


def test_format_summary_golden_two_sources(tmp_path):
    a = SourceCounts(
        source_file="ClientesFebrero2020.xls",
        source_year=2020,
        sheets_skipped=[],
        rows_read=10,
        split_extra=2,
        format_rejected=1,
        merged=1,
        conflicts=3,
        new=5,
        existing_updated=2,
        existing_unchanged=1,
        domain_rejected=1,
        unverified=1,
        personal=4,
        generic=6,
        missing_city=2,
        distinct_companies=7,
    )
    b = SourceCounts(
        source_file="Year Book 2009.xlsx",
        source_year=2009,
        sheets_skipped=["SQL", "Extra"],
        rows_read=20,
        split_extra=1,
        format_rejected=2,
        merged=2,
        conflicts=1,
        new=8,
        existing_updated=3,
        existing_unchanged=2,
        domain_rejected=2,
        unverified=2,
        personal=1,
        generic=2,
        missing_city=3,
        distinct_companies=9,
    )
    total = total_counts([a, b], distinct_companies=42)
    db_path = tmp_path / "b2b.sqlite3"
    rejects_path = tmp_path / "rejects.csv"
    review_path = tmp_path / "review.csv"

    expected = (
        "import_contacts: done\n"
        "source: ClientesFebrero2020.xls (year 2020)\n"
        "  sheets skipped:         -\n"
        "  rows read:                   10\n"
        "  extra from split cells:       2\n"
        "  rejected (format):            1\n"
        "  merged duplicates:            1\n"
        "  duplicate conflicts:          3\n"
        "  new contacts:                 5\n"
        "  existing updated:             2\n"
        "  existing unchanged:           1\n"
        "  rejected (domain):            1\n"
        "  unverified:                   1\n"
        "  personal:                     4\n"
        "  generic:                      6\n"
        "  missing city:                 2\n"
        "  distinct companies:           7\n"
        "source: Year Book 2009.xlsx (year 2009)\n"
        "  sheets skipped:         SQL, Extra\n"
        "  rows read:                   20\n"
        "  extra from split cells:       1\n"
        "  rejected (format):            2\n"
        "  merged duplicates:            2\n"
        "  duplicate conflicts:          1\n"
        "  new contacts:                 8\n"
        "  existing updated:             3\n"
        "  existing unchanged:           2\n"
        "  rejected (domain):            2\n"
        "  unverified:                   2\n"
        "  personal:                     1\n"
        "  generic:                      2\n"
        "  missing city:                 3\n"
        "  distinct companies:           9\n"
        "total\n"
        "  sheets skipped:         SQL, Extra\n"
        "  rows read:                   30\n"
        "  extra from split cells:       3\n"
        "  rejected (format):            3\n"
        "  merged duplicates:            3\n"
        "  duplicate conflicts:          4\n"
        "  new contacts:                13\n"
        "  existing updated:             5\n"
        "  existing unchanged:           3\n"
        "  rejected (domain):            3\n"
        "  unverified:                   3\n"
        "  personal:                     5\n"
        "  generic:                      8\n"
        "  missing city:                 5\n"
        "  distinct companies:          42\n"
        "  contacts not in sources:      4\n"
        f"database: {db_path} (13 contacts)\n"
        f"reports:  {rejects_path} (3 rows), {review_path} (2 rows)\n"
    )

    result = format_summary(
        [a, b],
        total,
        not_in_sources=4,
        db_path=db_path,
        contacts=13,
        rejects_path=rejects_path,
        rejects_rows=3,
        review_path=review_path,
        review_rows=2,
    )
    assert result == expected


def test_format_summary_trailing_newline(tmp_path):
    total = total_counts([], distinct_companies=0)
    result = format_summary(
        [],
        total,
        not_in_sources=0,
        db_path=tmp_path / "b2b.sqlite3",
        contacts=0,
        rejects_path=tmp_path / "rejects.csv",
        rejects_rows=0,
        review_path=tmp_path / "review.csv",
        review_rows=0,
    )
    assert result.endswith("\n")
    assert not result.endswith("\n\n")
