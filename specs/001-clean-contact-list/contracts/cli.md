# Contract: `import_contacts` command

**Feature**: 001-clean-contact-list

## Invocation

```text
.venv/bin/python -m b2b.import_contacts [options]
```

| Option | Default | Meaning |
|--------|---------|---------|
| `--clients PATH` | `contactos/ClientesFebrero2020.xls` | client file (source year 2020) |
| `--yearbook PATH` | `contactos/Year Book 2009.xlsx` | Year Book file (source year 2009) |
| `--db PATH` | `data/b2b.sqlite3` | database file; created with schema v1 if missing |
| `--reports-dir PATH` | `data/reports` | directory for `rejects.csv` and `review.csv`; created if missing |
| `--config-dir PATH` | `config` | directory holding `role_words.txt` and `cities.csv` |
| `--dns-workers N` | `16` | parallel domain lookups, 1–64 |
| `--dns-timeout SECONDS` | `3.0` | resolver lifetime per query, 0.5–30 |

No option sends email or changes tracking fields. There is no "dry run": the import never
contacts recipients, and a failed run changes nothing.

Python entry point for tests: `b2b.import_contacts.main(argv: list[str], checker=None) -> int`,
where `checker` is a `Callable[[str], DomainStatus]` replacing DNS.

## Exit codes

| Code | Meaning | Database | Reports |
|------|---------|----------|---------|
| 0 | success | committed | replaced |
| 1 | input or configuration error (missing file, missing header, unreadable config, invalid option) | unchanged | unchanged |
| 2 | database error, schema version newer than 1, or reconciliation mismatch | rolled back | unchanged |
| 130 | interrupted (Ctrl+C) | rolled back / untouched | unchanged |

## Standard output (success)

Counts only. Exact labels; numbers right-aligned in a column; one block per source then a total.

```text
import_contacts: done
source: ClientesFebrero2020.xls (year 2020)
  sheets skipped:        SQL
  rows read:             <n>
  extra from split cells:<n>
  rejected (format):     <n>
  merged duplicates:     <n>
  duplicate conflicts:   <n>
  new contacts:          <n>
  existing updated:      <n>
  existing unchanged:    <n>
  rejected (domain):     <n>
  unverified:            <n>
  personal:              <n>
  generic:               <n>
  missing city:          <n>
  distinct companies:    <n>
source: Year Book 2009.xlsx (year 2009)
  ...same labels...
total
  ...same labels...
  contacts not in sources: <n>
database: data/b2b.sqlite3 (<n> contacts)
reports:  data/reports/rejects.csv (<n> rows), data/reports/review.csv (<n> rows)
```

`sheets skipped` lists sheet names (not contact data) or `-`. `personal`, `generic`,
`missing city` and `distinct companies` count stored contacts (new + existing) by the
winner's source.

## Standard error

One line per problem, prefixed `import_contacts: error:`, naming the file, sheet, header,
option or setting involved. Never includes cell values, addresses or credentials.

Examples:

```text
import_contacts: error: Year Book 2009.xlsx sheet '3-100': missing header(s) CORREO
import_contacts: error: config/cities.csv: expected header 'variant,canonical'
import_contacts: error: data/b2b.sqlite3: schema version 3 is newer than this tool (1)
```
