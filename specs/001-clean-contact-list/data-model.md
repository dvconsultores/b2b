# Data Model: Clean Contact Database

**Feature**: 001-clean-contact-list | **Date**: 2026-09-13

## Stored: `contacts` table (SQLite, schema version 1)

| Column | Type | Constraints | Written by | Notes |
|--------|------|-------------|------------|-------|
| `id` | INTEGER | PRIMARY KEY | 001 insert | |
| `email` | TEXT | NOT NULL UNIQUE | 001 insert | normalized (plan D4) |
| `company` | TEXT | NOT NULL DEFAULT '' | 001 insert/refresh | winning row's text |
| `company_key` | TEXT | NOT NULL | 001 insert/refresh | `n:<name_key>` or `e:<email>` (D7) |
| `contact_name` | TEXT | NOT NULL DEFAULT '' | 001 insert/refresh | Year Book only |
| `city` | TEXT | NOT NULL DEFAULT '' | 001 insert/refresh | canonical or title-cased (D8) |
| `tax_id` | TEXT | NOT NULL DEFAULT '' | 001 insert/refresh | normalized RIF if valid, else as written |
| `area` | TEXT | NOT NULL DEFAULT '' | 001 insert/refresh | as written |
| `classification` | TEXT | NOT NULL CHECK IN ('personal','generic') | 001 insert/refresh | D6 |
| `source_file` | TEXT | NOT NULL | 001 insert/refresh | file base name |
| `source_sheet` | TEXT | NOT NULL | 001 insert/refresh | |
| `source_row` | INTEGER | NOT NULL CHECK > 0 | 001 insert/refresh | 1-based |
| `source_year` | INTEGER | NOT NULL CHECK IN (2009, 2020) | 001 insert/refresh | |
| `times_contacted` | INTEGER | NOT NULL DEFAULT 0 CHECK >= 0 | 002 only | |
| `last_contacted_at` | TEXT | NULL | 002 only | UTC ISO 8601 |
| `bounced` | INTEGER | NOT NULL DEFAULT 0 CHECK IN (0,1) | 002, 003 | |
| `bounced_at` | TEXT | NULL | 002, 003 | |
| `responded` | INTEGER | NOT NULL DEFAULT 0 CHECK IN (0,1) | 003 only | |
| `responded_at` | TEXT | NULL | 003 only | |
| `opted_out` | INTEGER | NOT NULL DEFAULT 0 CHECK IN (0,1) | 003 only | |
| `opted_out_at` | TEXT | NULL | 003 only | |
| `created_at` | TEXT | NOT NULL | 001 insert | UTC `YYYY-MM-DDTHH:MM:SSZ` |
| `updated_at` | TEXT | NOT NULL | 001 insert/refresh | changes only when a descriptive value changes |

Indexes: `UNIQUE(email)` (implicit), `idx_contacts_company_key` on `company_key`.

Table-level checks: `(bounced = 0) = (bounced_at IS NULL)`, same for `responded`/`responded_at`
and `opted_out`/`opted_out_at`; `(times_contacted = 0) = (last_contacted_at IS NULL)`.

### Tracking field rules (all specs)

- `times_contacted` only increases; `last_contacted_at` is set together with each increase.
- `bounced`, `responded`, `opted_out` only go from 0 to 1, with their date set in the same
  statement; nothing resets them.
- Spec 001 never includes any tracking column or `created_at` in an UPDATE (plan D10).
- Later specs add columns or tables through migrations that raise `user_version`
  (for example spec 002's send log).

### Descriptive refresh rule

On a re-run, an existing contact's company, company_key, contact_name, city, tax_id, area,
classification and source columns are replaced by this run's winning candidate only when at
least one value differs; `updated_at` is set only then.

## In memory (not stored)

- **SourceRow**: source_file, source_sheet, source_row, source_year, company, contact_name,
  city_raw, tax_id_raw, area, email_raw, company_contains_at (bool).
- **Candidate**: SourceRow + normalized email + order index (D3 order) + completeness (D9).
- **DomainStatus**: one of `accepts`, `domain_not_found`, `no_mail_server`, `null_mx`,
  `unverified` (D5).
- **RejectedRow**: source reference, email_raw, reason — `empty`, `invalid_format`,
  `non_ascii_local_part` (format, D4) or `domain_not_found`, `no_mail_server`, `null_mx`
  (domain, D5).
- **ReviewItem**: type, source reference (may be empty for aggregated items), detail, count.
  Types: `company_contains_at`, `multi_address_cell`, `invalid_token_in_multi_cell`,
  `city_not_in_mapping`, `unverified_domain`, `stored_domain_now_fails`.
- **RunSummary** (per source and total): rows_read, sheets_skipped (names), split_extra,
  format_rejected, merged, conflicts, new, existing_updated, existing_unchanged,
  domain_rejected, unverified, personal, generic, missing_city, distinct_companies; plus total
  `not_in_sources`.

### Reconciliation (plan D13)

Per source:

```text
rows_read + split_extra
  = format_rejected + merged + new + existing_updated + existing_unchanged
    + domain_rejected + unverified
```

`merged` is attributed to the losing candidate's source; the other terms to the winner's source.

## Flow

```text
SourceRow ──D4──► Candidate(s) ──D9──► winner per email ──D5──► accepts ──► contacts (insert/refresh)
    │                 │                     │                   ├─► rejected ──► rejects.csv
    │                 │                     └─ merged (count)   └─► unverified ─► review.csv
    │                 └─ no valid candidate ─► rejects.csv
    └─ anomalies (D4, D7, D8) ─► review.csv
```
