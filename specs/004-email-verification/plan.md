# Implementation Plan: Email Verification Before Sending

**Branch**: `004-email-verification` | **Date**: 2026-09-14 | **Spec**: [spec.md](spec.md)

## Technical Context

Python 3.13, standard library only (`csv`). No API integration: the operator moves files between
the server and the service's website. Schema v2 → v3.

## Constitution Check (v1.3.0)

| Principle | Status |
|-----------|--------|
| I. Sender Reputation First | Strengthened: only mailboxes confirmed by the service are sent to. |
| II. Never Contact Twice or Unwillingly | Strengthened: company exclusion across campaigns; export excludes suppressed contacts. |
| III. Plain, Human First Contact | N/A |
| IV. Contact Data Stays Local | Pass with amendment 1.3.0: email addresses only, named services, files under `data/` with 600/700 permissions. |
| V. Safe by Default | Import dry run; unrecognized statuses abort the import; export never overwrites. |
| VI. Simple, Reviewable Steps | Export and results are plain CSV files a person can open. No new dependency. |

## Pinned Decisions

- **D1 — Schema v3** (`b2b/store.py`): `ALTER TABLE contacts ADD COLUMN verification TEXT NOT NULL
  DEFAULT 'unverified' CHECK (verification IN ('unverified','valid','catch_all','unknown','invalid'))`
  and `verified_at TEXT`; `_migrate_2_to_3` in one transaction; `SCHEMA_VERSION = 3`.
- **D2 — Status mapping** (`b2b/verification.py`): valid, deliverable → `valid`; catchall,
  catch-all, catch_all, accept_all, accept-all → `catch_all`; unknown, risky → `unknown`;
  invalid, undeliverable, disposable, spamtrap, abuse, do_not_mail → `invalid` (case-insensitive).
  Email column headers: email, email address, e-mail, emailaddress. Status headers in order:
  zb status, result, neverbounce result, email status, email_status, verification status, status.
  UTF-8 (BOM allowed); delimiter sniffed among `,` `;` tab. Last row for an address wins.
- **D3 — Eligibility** (`b2b/eligibility.py`): spec 002 D8 plus (a) company exclusion no longer
  filters by campaign (any step-1 `accepted`/`pending`/`unknown` attempt), (b)
  `select_recipients(conn, campaign, step, allowed_verification=("valid",))` keeps only candidates
  whose verification is allowed before choosing one per company; `Selection.skipped_not_verified`.
  `verification_candidates(conn, step=1)` returns the unverified candidate emails ordered by id.
- **D4 — Campaign** (`b2b/campaign.py`): optional `allowed_verification` list, default `["valid"]`,
  non-empty, no duplicates, subset of `valid`, `catch_all`, `unknown`. Config renamed to
  `primer-contacto-2026-b`.
- **D5 — Export** (`b2b/export_verification.py`): `--db`, `--out-dir` (default `data/verification`);
  file `verify-emails-<UTC YYYYMMDD-HHMMSS>.csv`, header `email`, directory 700, file 600, `O_EXCL`;
  nothing to export → no file, exit 0. Exit 1 write error / exists, 2 database.
- **D6 — Import** (`b2b/import_verification.py`): positional results file, `--db`,
  `--email-column`, `--status-column`, `--dry-run`; any unrecognized status → exit 1, nothing
  written, counts only; one transaction; prints rows, blank email, matched, not in database and
  per-status counts. Exit 1 input error, 2 database.
- **D7 — Summary**: new line `skipped not verified:` after `eligible contacts:`.
- **D8 — Container**: `export-verification`; `import-verification <file> [options]` (relative names
  resolve to `/app/data/verification/`).

## Project Structure

```text
b2b/store.py  b2b/verification.py  b2b/export_verification.py  b2b/import_verification.py
b2b/eligibility.py  b2b/campaign.py  b2b/send_report.py  b2b/send_first_email.py
config/campaign.toml  docker-entrypoint.sh
tests/test_verification.py  tests/test_eligibility.py  tests/test_store.py  tests/test_campaign.py
tests/conftest.py (synthetic contacts default to verified)
```

## Complexity Tracking

None.
