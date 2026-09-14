# Implementation Plan: Clean Contact Database

**Branch**: `001-clean-contact-list` (no git) | **Date**: 2026-09-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-clean-contact-list/spec.md`

## Summary

A command-line import reads both contact spreadsheets, normalizes and validates every address,
merges duplicates, checks each distinct domain in DNS, classifies personal vs generic, and
upserts only mail-accepting addresses into a local SQLite database whose tracking fields
(times contacted, bounced, responded, opted out) are created here and never touched by
re-runs. Rejected rows and anomalies go to CSV reports; the screen shows counts only. All
DNS work happens before a single database transaction, so a failed run changes nothing.

## Technical Context

**Language/Version**: Python 3.13.5 (`.venv/`)

**Primary Dependencies**: xlrd 2.0.2 (.xls), openpyxl 3.1.5 (.xlsx), dnspython 2.8.0 (MX/A/AAAA
lookups); standard library `sqlite3`, `csv`, `argparse`, `concurrent.futures`, `unicodedata`

**Storage**: SQLite file `data/b2b.sqlite3` (schema version 1); CSV reports in `data/reports/`

**Testing**: pytest 9.1.1, synthetic fixtures only, network blocked in tests

**Target Platform**: Linux workstation (Debian 13), run by the operator

**Project Type**: Single-project CLI tool

**Performance Goals**: full run < 5 minutes (SC-006); 895 distinct domains, 16 lookup workers,
3-second lifetime per query → typical ≈ 20 s, worst case (every domain times out) ≈ 170 s

**Constraints**: stdout/stderr never show contact values (FR-013); database unchanged on any
failure (FR-012); no network other than DNS (FR-015); tracking fields never modified (FR-011)

**Scale/Scope**: 2,907 source data rows, 2,791 unique addresses, 895 distinct domains
(2 internationalized), 14 data sheets across 2 files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Sender Reputation First | Pass | Only addresses whose domain accepts mail are stored (D5); unverified addresses are not stored. No sending in this feature. |
| II. Never Contact Twice or Unwillingly | Pass | `email` is UNIQUE; tracking fields `times_contacted`, `bounced`, `responded`, `opted_out` exist from schema v1 and are never written by the import (D10). |
| III. Plain, Human First Contact | N/A | No email is composed or sent. |
| IV. Contact Data Stays Local | Pass | Database and reports live in `data/` on this machine; only domain names leave it, via DNS — the exception approved in the spec. Summary prints counts only (D11). Tests use synthetic data (D14). `data/` added to the DeepSeek egress rule (D15). |
| V. Safe by Default | Pass | Import never deletes or resets; single transaction with rollback; reports replaced atomically after commit (D10, D11). |
| VI. Simple, Reviewable Steps | Pass | Three runtime libraries, each justified in research.md (R1–R3); SQLite and CSV are local files; CSV reports open in a spreadsheet. |

## Pinned Decisions

Implementation tasks must follow these exactly; changes require a plan update.

- **D1 — Layout**: package `b2b/` with modules `sources.py`, `emails.py`, `domains.py`,
  `companies.py`, `cities.py`, `classify.py`, `merge.py`, `store.py`, `reports.py`,
  `import_contacts.py`; operator-editable files in `config/`; runtime output in `data/`;
  tests in `tests/`. See Project Structure.
- **D2 — Dependencies**: `requirements.txt` pins `xlrd==2.0.2`, `openpyxl==3.1.5`,
  `dnspython==2.8.0`, `python-dotenv==1.2.3` (already installed at the operator's request; used
  by specs 002–003, not imported by this feature). `requirements-dev.txt` pins `pytest==9.1.1`.
  Installing them into `.venv` is the first task and needs implementation authorization.
- **D3 — Reading sources**: header row is row 1; headers compared after trimming and
  uppercasing. Client file (`ClientesFebrero2020.xls`, via xlrd) requires `RIF`, `NOMBRE`,
  `CIUDAD`, `MAIL`, `AREA`; Year Book (`Year Book 2009.xlsx`, via openpyxl `read_only=True,
  data_only=True`) requires `EMPRESA`, `CONTACTO`, `CORREO`, `CIUDAD` on every sheet. A sheet
  with no non-blank rows, or only the header row, is skipped and named in the summary. Any
  other sheet missing a required header raises an input error (file, sheet, missing header
  names) before anything is written. Fully blank data rows are ignored and not counted. Row
  numbers are 1-based spreadsheet rows. Numeric cells that hold whole numbers become text
  without a decimal part (`12345.0` → `12345`). Descriptive text is trimmed with internal
  whitespace collapsed. Source year comes from the source kind (client file 2020, Year Book
  2009), not from the file name. Sources are processed in order: client file sheets, then
  Year Book sheets in workbook order.
- **D4 — Addresses**: a cell with at most one `@` yields one candidate: remove all Unicode
  whitespace, lowercase, remove a leading `mailto:`, strip leading/trailing characters in
  `.,;:<>()[]"'`. A cell with two or more `@` is split on `[;,/\s]+`; tokens containing `@`
  are normalized the same way; the row gets a `multi_address_cell` review item when it yields
  two or more valid candidates, and an `invalid_token_in_multi_cell` item per invalid token
  when at least one token is valid. Validation (in order, first failure is the reason):
  empty → `empty`; not exactly one `@`, empty local part or domain → `invalid_format`;
  non-ASCII local part → `non_ascii_local_part`; local part longer than 64 or not matching
  `^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$` → `invalid_format`;
  domain longer than 253, fewer than 2 labels, any label empty/longer than 63/starting or
  ending with `-`/containing characters other than letters, digits and `-`, a TLD that is not
  all letters of length ≥ 2, or a domain that fails `str.encode("idna")` → `invalid_format`.
  Stored addresses keep the Unicode domain as written (lowercase). A row whose cell yields no
  valid candidate becomes one rejected row with the first token's reason.
- **D5 — Domain check**: each distinct domain of the deduplicated addresses is checked once,
  with `concurrent.futures.ThreadPoolExecutor(max_workers=16)` and a dnspython resolver using
  the system configuration and `lifetime=3.0`. The IDNA-encoded name is queried for MX: an
  answer consisting only of preference 0 and exchange `.` → `null_mx`; any other MX answer →
  `accepts`; NXDOMAIN → `domain_not_found`; NoAnswer → query A, then AAAA: any answer →
  `accepts` (implicit MX), NXDOMAIN → `domain_not_found`, both NoAnswer → `no_mail_server`;
  Timeout, NoNameservers or any other DNS exception → `unverified`. The checker is a
  function `check_domain(domain: str) -> DomainStatus` injected into the import so tests use
  a fake; results are handled in sorted domain order.
- **D6 — Classification**: `config/role_words.txt`, one word per line, `#` comments and blank
  lines ignored, compared lowercase. The local part is reduced by removing trailing digits
  and then all `.`, `-`, `_`; if the result is in the list the address is `generic`,
  otherwise `personal`. Initial list: info, informacion, ventas, venta, contacto, contactos,
  admin, administracion, administrativo, rrhh, rh, recursoshumanos, compras, gerencia,
  gerenciageneral, recepcion, facturacion, cobranza, cobranzas, pagos, tesoreria,
  contabilidad, servicio, servicios, atencion, atencionalcliente, clientes, mercadeo,
  marketing, soporte, sistemas, proyectos, sales, contact, office, oficina, comercial,
  presidencia, mail, correo, operaciones, logistica, nomina, webmaster, postmaster, noreply.
- **D7 — Company key**: `name_key` = NFKD, drop combining marks, casefold, replace every
  non-alphanumeric character with a space, collapse spaces, then repeatedly remove a trailing
  legal suffix token sequence from: `c a`, `ca`, `s a`, `sa`, `s r l`, `srl`,
  `compania anonima`, `sociedad anonima`; an empty result falls back to the casefolded
  original. `tax_id` normalization = uppercase, remove non-alphanumerics; it is used for
  grouping only when it matches `^[VEJPG]\d{8,9}$`, otherwise it is stored as written
  (trimmed). Keys are assigned with union-find over all source rows: rows sharing a non-empty
  `name_key` are joined, and rows sharing a valid normalized tax ID are joined; each
  component's key is `n:` + the `name_key` of its earliest row. Rows with no company name and
  no valid tax ID get `e:` + their normalized address. Stored `company` is the winning row's
  company text (D3 whitespace rules); display casing belongs to spec 002. A company cell that
  contains `@` adds a `company_contains_at` review item.
- **D8 — Cities**: `config/cities.csv` (UTF-8, header `variant,canonical`). Match key = NFKD,
  drop combining marks, casefold, punctuation to spaces, collapse spaces. A mapped value
  becomes its canonical name. An unmapped value is stored title-cased word by word, with
  `de`, `del`, `la`, `las`, `los`, `y` lowercase except as the first word, and adds one
  aggregated `city_not_in_mapping` review item per distinct match key (detail = first value
  as written, count = rows). Empty city stays empty and counts as missing city. Initial
  mapping contains public city-name variants only (for example `ccs`/`caracas` → Caracas,
  `san cristobal` → San Cristóbal, `merida` → Mérida, `maturin` → Maturín, `cumana` →
  Cumaná).
- **D9 — Deduplication**: candidates are grouped by normalized address. Completeness =
  number of non-empty fields among company, contact name, city, tax ID, area. The winner is the
  highest completeness, ties to the earliest candidate in D3 order. Every other candidate in
  the group counts as merged (attributed to its own source). A group whose non-empty
  company `name_key`s or city match keys differ counts one conflict. Pipeline order: read →
  extract/validate → company keys → deduplicate → domain check on winners → classify and map
  cities → store / reject / unverified.
- **D10 — Storage**: schema in [data-model.md](data-model.md); `PRAGMA user_version = 1`;
  `ensure_schema` creates v1 on an empty file and refuses a higher version. All DNS lookups
  finish before `BEGIN IMMEDIATE`; the upsert runs in that one transaction and rolls back on
  any exception. New address → insert with tracking defaults and `created_at` =
  `updated_at` = run time (UTC, `YYYY-MM-DDTHH:MM:SSZ`). Existing address → update company,
  company key, contact name, city, tax ID, area, classification and source columns only when
  at least one differs, then set `updated_at`; tracking columns and `created_at` are never
  in any UPDATE. An existing address whose domain now fails or is unverified is not changed
  and gets a `stored_domain_now_fails` review item. Contacts absent from the sources are left
  alone and counted as `not_in_sources`.
- **D11 — Reports and output**: CSV, `utf-8-sig`, comma-separated, header row, written to a
  temporary file in the reports directory and moved into place with `os.replace` after the
  commit. Formats, codes and the stdout summary layout are in [contracts/](contracts/).
  Errors go to stderr naming file, sheet or setting, never contact values. No log files.
- **D12 — CLI**: `python -m b2b.import_contacts` with options and exit codes in
  [contracts/cli.md](contracts/cli.md). `main(argv, checker=None)` accepts an injected domain
  checker for tests.
- **D13 — Reconciliation**: per source, rows read + extra candidates from split cells =
  format-rejected rows + merged + new + existing + domain-rejected + unverified. The run
  asserts this before committing; a mismatch is a bug and aborts the run (exit 2).
- **D14 — Tests**: pytest; `tests/conftest.py` has an autouse fixture that makes
  `socket.socket` and `dns.resolver.Resolver.resolve` raise, a fake checker built from a dict,
  an openpyxl-built Year Book in `tmp_path`, a stub for `xlrd.open_workbook` returning
  synthetic sheets, and a temporary database path. Synthetic addresses use `example.com`,
  `example.org` and `example.net` only. No test reads `contactos/`, `.env` or `data/`.
- **D15 — Data handling**: `data/` holds real personal data (database and reports). It is added
  to the egress rule in `.claude/CLAUDE.md` and to the DeepSeek executor's never-open list.

## Project Structure

### Documentation (this feature)

```text
specs/001-clean-contact-list/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── cli.md           # command, options, exit codes, summary output
│   └── files.md         # config files, report files
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks) — not created here
```

### Source Code (project root)

```text
b2b/
├── __init__.py
├── sources.py          # D3: read both workbooks → SourceRow
├── emails.py           # D4: extract, normalize, validate addresses
├── domains.py          # D5: DNS checker + parallel check of distinct domains
├── companies.py        # D7: name_key, tax ID normalization, union-find company keys
├── cities.py           # D8: mapping load, match key, title-casing
├── classify.py         # D6: role-word list load, personal/generic
├── merge.py            # D9: candidate grouping, winner, merged/conflict counts
├── store.py            # D10: schema v1, transaction, upsert preserving tracking
├── reports.py          # D11: rejects/review CSV, summary text
└── import_contacts.py  # D12/D13: CLI, pipeline, reconciliation
config/
├── role_words.txt      # D6
└── cities.csv          # D8
data/                   # created at runtime — REAL PERSONAL DATA
├── b2b.sqlite3
└── reports/
    ├── rejects.csv
    └── review.csv
tests/
├── conftest.py
├── test_sources.py
├── test_emails.py
├── test_domains.py
├── test_companies.py
├── test_cities.py
├── test_classify.py
├── test_merge.py
├── test_store.py
├── test_reports.py
└── test_import_contacts.py
requirements.txt
requirements-dev.txt
```

**Structure Decision**: single project with one package; each module maps to one pinned
decision so tasks stay within one or two files.

## Delegation Notes (for /speckit-tasks)

- Likely DEEPSEEK: `emails.py`, `classify.py`, `cities.py`, `companies.py`, `reports.py`,
  `sources.py` and their tests — every rule is pinned above, inputs are synthetic.
- CLAUDE: `store.py` (tracking-field preservation and transaction safety guard the send path),
  `domains.py` (network behavior and failure classification), `merge.py` (decides which record
  represents a contact), `import_contacts.py` (orchestration, reconciliation, rollback), and
  `conftest.py` network guard.

## Post-Design Constitution Re-check

All six gates still pass after Phase 1: the data model keeps tracking columns out of every
import write path (II), the contracts print counts only and keep reports local (IV), and the
only new files are local SQLite/CSV (VI). No violations; Complexity Tracking is empty.

## Complexity Tracking

No constitution violations to justify.
