# Quickstart: Clean Contact Database

**Feature**: 001-clean-contact-list

Validation guide proving the feature works. Commands run from the project root.

## Prerequisites

- The user has authorized implementation of spec 001.
- `.venv/` exists with Python 3.13.
- Dependencies installed (first implementation task):

  ```bash
  .venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
  ```

## 1. Automated tests (synthetic data, no network)

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass. Coverage per requirement:

| Scenario | Proves |
|----------|--------|
| Case/space normalization, invalid and empty cells, non-ASCII local part | FR-002, US1-2/3 |
| Fake checker returns `domain_not_found`, `no_mail_server`, `null_mx`, `unverified` | FR-003, US1-4/5 |
| Same address in three rows with different completeness | FR-004, US1-6 |
| Two addresses with the same company name and different spacing/suffix; shared RIF | FR-005, US1-7 |
| Header-only and empty sheets | FR-001, US1-8 |
| Two-address cell | US1-9 |
| Role words with digits and separators | FR-006, US3 |
| Mapped, unmapped and empty cities | FR-007 |
| New contact defaults; re-run after tracking fields changed; new row on re-run; existing contact whose domain now fails | FR-010, FR-011, US2 |
| Exception injected during upsert leaves the database identical | FR-012 |
| Missing header → exit 1, nothing written | edge case |
| Two runs with the same inputs and checker → identical table contents | SC-004 |
| Summary contains no synthetic address, company or city values; totals reconcile | FR-013, SC-001 |
| Any attempt to open a socket fails the test | FR-015 |

## 2. Real import (needs explicit user authorization for this run)

The run reads `contactos/` and performs DNS lookups of domain names only. Per
`.claude/CLAUDE.md`, ask the user before running it.

```bash
.venv/bin/python -m b2b.import_contacts
```

Expected outcome (from the 2026-09-13 profile; exact numbers depend on DNS answers):

- Client file: rows read 1,620, sheet `SQL` skipped.
- Year Book: rows read 1,287, sheet `14-100` skipped.
- About 21 format rejections in total; zero cross-file duplicates; about 90 merged duplicates in
  the client file.
- Exit code 0, reconciliation holds, output shows counts only.

## 3. Database checks (counts only)

```bash
.venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("data/b2b.sqlite3")
q = lambda s: c.execute(s).fetchone()[0]
print("schema version:", q("PRAGMA user_version"))
print("contacts:", q("SELECT COUNT(*) FROM contacts"))
print("duplicate emails:", q("SELECT COUNT(*) - COUNT(DISTINCT email) FROM contacts"))
print("tracking non-default:", q("SELECT COUNT(*) FROM contacts WHERE times_contacted>0 OR bounced OR responded OR opted_out"))
print("personal / generic:", q("SELECT SUM(classification='personal') FROM contacts"), q("SELECT SUM(classification='generic') FROM contacts"))
EOF
```

Expected: schema version 1 (2 once any spec 002 command has opened the database), zero
duplicate emails, tracking non-default 0 on a fresh import.

## 4. Re-run safety

1. Run the import again with no source changes: exit 0, `new contacts: 0`,
   `existing updated: 0`.
2. In a copy of the database (never the real one), set tracking fields on a few contacts,
   run the import with `--db` pointing at the copy, and confirm those values are unchanged.

## 5. Manual classification check (SC-003)

Open `data/b2b.sqlite3` in a local SQLite viewer, pick 50 random contacts, and confirm at least
48 are correctly labeled personal or generic. Add missed role words to
`config/role_words.txt` and re-run.

## 6. Review the reports

Open `data/reports/rejects.csv` and `data/reports/review.csv` in a spreadsheet program; extend
`config/cities.csv` for unmapped cities that should be merged, then re-run.
