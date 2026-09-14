"""Import both contact spreadsheets into the contact database (spec 001).

Usage: python -m b2b.import_contacts [options] — see specs/001-clean-contact-list/contracts/cli.md.
Prints counts only; never prints contact values.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

from b2b import ConfigError, InputError, store
from b2b.cities import CityMap, aggregate_unmapped_cities, load_city_map, normalize_city
from b2b.classify import classify, load_role_words
from b2b.companies import assign_company_keys, stored_tax_id
from b2b.domains import REJECT_STATUSES, DomainStatus, check_domains, make_dns_checker
from b2b.emails import domain_of, extract
from b2b.merge import Candidate, Group, group_candidates
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
from b2b.sources import SourceRead, SourceRow, read_clients, read_yearbook
from b2b.store import ContactValues

PROG = "import_contacts"


class _ArgumentError(Exception):
    pass


class _ReconciliationError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise _ArgumentError(message)


def _error(message: str) -> None:
    print(f"{PROG}: error: {message}", file=sys.stderr)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _Parser(prog=f"python -m b2b.{PROG}", description="Import contacts into the database.")
    parser.add_argument("--clients", default="contactos/ClientesFebrero2020.xls")
    parser.add_argument("--yearbook", default="contactos/Year Book 2009.xlsx")
    parser.add_argument("--db", default="data/b2b.sqlite3")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--dns-workers", type=int, default=16)
    parser.add_argument("--dns-timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    if not 1 <= args.dns_workers <= 64:
        raise _ArgumentError("--dns-workers must be between 1 and 64")
    if not 0.5 <= args.dns_timeout <= 30:
        raise _ArgumentError("--dns-timeout must be between 0.5 and 30")
    return args


def _ref(row: SourceRow) -> SourceRef:
    return SourceRef(row.source_file, row.source_sheet, row.source_row)


def _read_source(reader: Callable[[Path], SourceRead], path: Path) -> SourceRead:
    try:
        return reader(path)
    except (InputError, OSError):
        raise
    except Exception as exc:  # corrupt workbook: report the type, never cell contents
        raise InputError(f"{path}: cannot read workbook ({type(exc).__name__})") from None


def _contact_values(
    candidate: Candidate, role_words: frozenset[str], city_map: CityMap
) -> tuple[ContactValues, bool]:
    row = candidate.row
    city, needs_review = normalize_city(row.city_raw, city_map)
    values = ContactValues(
        email=candidate.email,
        company=row.company,
        company_key=candidate.company_key,
        contact_name=row.contact_name,
        city=city,
        tax_id=stored_tax_id(row.tax_id_raw),
        area=row.area,
        classification=classify(candidate.email, role_words),
        source_file=row.source_file,
        source_sheet=row.source_sheet,
        source_row=row.source_row,
        source_year=row.source_year,
    )
    return values, needs_review


def main(
    argv: list[str] | None = None, checker: Callable[[str], DomainStatus] | None = None
) -> int:
    try:
        args = _parse_args(argv)
    except _ArgumentError as exc:
        _error(str(exc))
        return 1
    try:
        return _run(args, checker)
    except KeyboardInterrupt:
        _error("interrupted; nothing was written")
        return 130


def _run(args: argparse.Namespace, checker: Callable[[str], DomainStatus] | None) -> int:
    config_dir = Path(args.config_dir)
    try:
        role_words = load_role_words(config_dir / "role_words.txt")
        city_map = load_city_map(config_dir / "cities.csv")
        sources = [
            _read_source(read_clients, Path(args.clients)),
            _read_source(read_yearbook, Path(args.yearbook)),
        ]
    except (ConfigError, InputError) as exc:
        _error(str(exc))
        return 1
    except OSError as exc:
        _error(f"{exc.filename}: {exc.strerror or 'cannot read file'}")
        return 1

    counts = {
        source.source_file: SourceCounts(
            source_file=source.source_file,
            source_year=source.source_year,
            sheets_skipped=list(source.skipped_sheets),
            rows_read=len(source.rows),
        )
        for source in sources
    }
    rejected: list[RejectedRow] = []
    review: list[ReviewItem] = []

    # Extract and validate addresses (D4).
    pending: list[tuple[SourceRow, str]] = []
    for source in sources:
        for row in source.rows:
            ref = _ref(row)
            source_counts = counts[row.source_file]
            if row.company_contains_at:
                review.append(ReviewItem("company_contains_at", ref, row.company))
            extraction = extract(row.email_raw)
            if not extraction.candidates:
                reason = extraction.invalid[0][1] if extraction.invalid else "empty"
                rejected.append(RejectedRow(ref, row.email_raw, reason))
                source_counts.format_rejected += 1
                continue
            source_counts.split_extra += len(extraction.candidates) - 1
            if len(extraction.candidates) >= 2:
                review.append(ReviewItem("multi_address_cell", ref, row.email_raw))
            for token, _reason in extraction.invalid:
                review.append(ReviewItem("invalid_token_in_multi_cell", ref, token))
            pending.extend((row, email) for email in extraction.candidates)

    # Company keys (D7) and deduplication (D9).
    keys = assign_company_keys([(row.company, row.tax_id_raw, email) for row, email in pending])
    candidates = [
        Candidate(row=row, email=email, order=index, company_key=key)
        for index, ((row, email), key) in enumerate(zip(pending, keys))
    ]
    groups: list[Group] = group_candidates(candidates)
    for group in groups:
        if group.conflict:
            counts[group.winner.row.source_file].conflicts += 1
        for member in group.merged:
            counts[member.row.source_file].merged += 1

    # Domain check (D5) — all network work finishes before the database is touched.
    statuses = check_domains(
        {domain_of(group.winner.email) for group in groups},
        checker or make_dns_checker(args.dns_timeout),
        args.dns_workers,
    )

    db_path = Path(args.db)
    try:
        conn = store.connect(db_path)
    except Exception as exc:
        _error(f"{db_path}: cannot open database ({type(exc).__name__})")
        return 2
    try:
        try:
            store.ensure_schema(conn)
        except store.SchemaError as exc:
            _error(str(exc))
            return 2
        existing = store.existing_emails(conn)

        queued: list[ContactValues] = []
        stored: list[ContactValues] = []
        unmapped_cities: list[str] = []
        for group in groups:
            winner = group.winner
            ref = _ref(winner.row)
            source_counts = counts[winner.row.source_file]
            status = statuses[domain_of(winner.email)]
            if status == "accepts":
                values, needs_review = _contact_values(winner, role_words, city_map)
                queued.append(values)
                stored.append(values)
                if needs_review:
                    unmapped_cities.append(winner.row.city_raw)
            elif winner.email in existing:
                # Never remove or alter a stored contact because its domain now fails (US2-4).
                values, _ = _contact_values(winner, role_words, city_map)
                stored.append(values)
                source_counts.existing_unchanged += 1
                review.append(ReviewItem("stored_domain_now_fails", ref, f"{winner.email} ({status})"))
            elif status in REJECT_STATUSES:
                rejected.append(RejectedRow(ref, winner.row.email_raw, status))
                source_counts.domain_rejected += 1
            else:
                review.append(ReviewItem("unverified_domain", ref, winner.email))
                source_counts.unverified += 1
        review.extend(aggregate_unmapped_cities(unmapped_cities))

        all_companies: set[str] = set()
        companies_by_source: dict[str, set[str]] = {name: set() for name in counts}
        for values in stored:
            source_counts = counts[values.source_file]
            if values.classification == "generic":
                source_counts.generic += 1
            else:
                source_counts.personal += 1
            if not values.city:
                source_counts.missing_city += 1
            companies_by_source[values.source_file].add(values.company_key)
            all_companies.add(values.company_key)
        for name, keys_seen in companies_by_source.items():
            counts[name].distinct_companies = len(keys_seen)

        reports_dir = Path(args.reports_dir)
        rejects_path = reports_dir / "rejects.csv"
        review_path = reports_dir / "review.csv"
        staged: list[Path] = []
        try:
            staged.append(stage_rejects(reports_dir, rejected))
            staged.append(stage_review(reports_dir, review))
            source_of = {values.email: values.source_file for values in queued}
            with store.transaction(conn):
                result = store.upsert_contacts(conn, queued, store.utc_now())
                for email in result.new:
                    counts[source_of[email]].new += 1
                for email in result.updated:
                    counts[source_of[email]].existing_updated += 1
                for email in result.unchanged:
                    counts[source_of[email]].existing_unchanged += 1
                mismatched = [c.source_file for c in counts.values() if not reconciles(c)]
                if mismatched:
                    raise _ReconciliationError(", ".join(mismatched))
            contacts = store.count_contacts(conn)
            publish(staged[0], rejects_path)
            publish(staged[1], review_path)
            staged = []
        except _ReconciliationError as exc:
            _error(f"counts do not reconcile for {exc}; nothing was written")
            return 2
        except Exception as exc:
            _error(f"import failed ({type(exc).__name__}); database unchanged")
            return 2
        finally:
            for path in staged:
                discard(path)

        not_in_sources = len(existing - {group.winner.email for group in groups})
        per_source = list(counts.values())
        print(
            format_summary(
                per_source,
                total_counts(per_source, len(all_companies)),
                not_in_sources,
                db_path,
                contacts,
                rejects_path,
                len(rejected),
                review_path,
                len(review),
            ),
            end="",
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
