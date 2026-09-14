# Research: Clean Contact Database

**Feature**: 001-clean-contact-list | **Date**: 2026-09-13

Inputs measured on 2026-09-13 (aggregates only): 2,907 data rows, 2,791 unique addresses,
895 distinct domains (578 used by a single address, 2 with non-ASCII characters), about half of
all addresses on a handful of free-mail/ISP domains. Latest package versions from the Python
package index on the same day.

## R1 — Reading the .xls client file

- **Decision**: xlrd 2.0.2.
- **Rationale**: xlrd 2.x reads exactly the legacy `.xls` format, is pure Python, and is already
  installed; the profile run read all 1,620 rows with it.
- **Alternatives considered**: pandas (large dependency that delegates to xlrd for `.xls`
  anyway); converting with LibreOffice (external binary, extra step for the operator);
  pyexcel-xls (wrapper around xlrd with more dependencies).

## R2 — Reading the .xlsx Year Book

- **Decision**: openpyxl 3.1.5 with `read_only=True, data_only=True`.
- **Rationale**: the standard, maintained pure-Python reader; handles shared strings, inline
  strings, numbers and dates correctly; read-only mode is fast for 14 small sheets.
- **Alternatives considered**: the standard-library zip/XML parser used for profiling (works on
  this file but fragile for dates, rich text and styles — not acceptable for a tool that
  decides who is emailed); pandas (heavy); python-calamine (native wheels, less common).

## R3 — Checking that a domain accepts mail

- **Decision**: dnspython 2.8.0 — MX query; null MX (RFC 7505) rejects; no MX falls back to
  A/AAAA (implicit MX, RFC 5321 §5.1); NXDOMAIN rejects; timeouts and server failures mark the
  address unverified.
- **Rationale**: the standard library cannot query MX records. dnspython is the de-facto Python
  DNS library, distinguishes NXDOMAIN, NoAnswer and timeouts (needed to separate rejected from
  unverified), and handles internationalized names.
- **Alternatives considered**: calling `dig` in a subprocess (depends on an installed binary,
  output parsing); `socket.getaddrinfo` (A/AAAA only, cannot see MX or null MX); SMTP
  `RCPT TO` probing (contacts the recipient's mail server — excluded by the spec and harmful
  to reputation); third-party verification APIs (send addresses to a third party — excluded
  by the spec and Constitution IV).

## R4 — Lookup concurrency and timeouts

- **Decision**: 16 worker threads, 3-second resolver lifetime, one lookup per distinct domain,
  A/AAAA fallback only after a NoAnswer.
- **Rationale**: 895 domains × typical 0.1–0.3 s ÷ 16 ≈ 10–20 s. A timeout ends that domain's
  checks, so the worst case (all time out) is 895 × 3 s ÷ 16 ≈ 170 s, inside the 5-minute
  target (SC-006). Sixteen parallel queries is light load for any resolver.
- **Alternatives considered**: sequential lookups (worst case ≈ 45 minutes); asyncio with
  dnspython's async resolver (same result, more code); higher concurrency (risks resolver
  rate limiting for no user-visible gain).

## R5 — Address validation rule

- **Decision**: pragmatic rule pinned in plan D4 — dot-atom ASCII local part, letter/digit/
  hyphen domain labels (Unicode allowed, must IDNA-encode), alphabetic TLD.
- **Rationale**: B2B mailboxes never use quoted local parts or IP literals; rejecting them
  costs nothing and removes a class of bounces. Non-ASCII local parts need SMTPUTF8, which the
  send path does not rely on.
- **Alternatives considered**: full RFC 5322 grammar (accepts addresses that real providers
  reject); the `email-validator` package (extra dependency with its own DNS behavior that would
  overlap R3).

## R6 — Storage

- **Decision**: standard-library `sqlite3`, one file, `PRAGMA user_version` for schema
  versions, one `BEGIN IMMEDIATE` transaction per run.
- **Rationale**: user requirement (SQLite); transactions give FR-012; `user_version` lets specs
  002 and 003 add columns and tables with small, ordered migrations.
- **Alternatives considered**: SQLAlchemy/Alembic (far more than a single-table store needs);
  CSV tracker (no atomic updates, easy to corrupt tracking fields).

## R7 — Report file format

- **Decision**: CSV encoded `utf-8-sig`.
- **Rationale**: opens directly in Excel and LibreOffice with accents intact (the BOM makes
  Excel detect UTF-8); no dependency; easy to diff between runs.
- **Alternatives considered**: `.xlsx` via openpyxl (heavier, not text); plain UTF-8 CSV
  (Excel on Windows misreads accents).

## R8 — Grouping rows into companies

- **Decision**: union-find joining rows that share a normalized company name or a valid RIF;
  key taken from the earliest row's normalized name.
- **Rationale**: the Year Book has no RIF, so RIF-only keys cannot group across files; name-only
  keys miss a company written two ways that shares a RIF. Union-find covers both
  deterministically.
- **Alternatives considered**: RIF only; name only; fuzzy name matching (non-deterministic
  thresholds, hard to review).

## R9 — Re-runs and identical output

- **Decision**: update an existing contact only when a descriptive value differs; write
  timestamps only on insert or real change.
- **Rationale**: SC-004 requires identical database contents on a repeated run; unconditional
  updates would change `updated_at` every time. Tracking columns are never in an UPDATE (FR-011).
- **Alternatives considered**: rebuild the table each run (would destroy tracking data);
  import-run history table (changes contents every run, breaking SC-004).

## R10 — Keeping tests off the network and real data

- **Decision**: autouse pytest fixture that makes socket creation and dnspython resolution raise;
  domain checker injected into `main`; `.xls` reading tested through a stubbed
  `xlrd.open_workbook`.
- **Rationale**: Constitution workflow rule — no test opens a network connection or reads
  `contactos/`. Writing real `.xls` fixtures would need the unmaintained xlwt package.
- **Alternatives considered**: xlwt for fixtures (extra, unmaintained dev dependency); marking
  network tests and skipping them (still allows accidental network use).

## R11 — python-dotenv

- **Decision**: pinned in `requirements.txt` (1.2.3) but not imported by this feature.
- **Rationale**: the operator asked for it; specs 002 and 003 read SMTP and mailbox settings from
  `.env`. Pinning now keeps one requirements file in sync with `.venv`.
- **Alternatives considered**: add it in spec 002's plan (would leave an installed but
  undeclared package in `.venv`).
