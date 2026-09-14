# Contract: configuration and report files

**Feature**: 001-clean-contact-list

## `config/role_words.txt` (operator-editable)

- UTF-8 text, one role word per line, compared lowercase.
- Lines starting with `#` and blank lines are ignored; surrounding whitespace is trimmed.
- Words must be letters only after the plan D6 reduction (no dots, hyphens, underscores or
  digits); a line that is not is a configuration error (exit 1) naming the line number.
- Initial content: the list in plan D6.

## `config/cities.csv` (operator-editable)

- UTF-8 (a BOM is accepted), comma-separated, header exactly `variant,canonical`.
- `variant`: any spelling; matched through the plan D8 match key.
- `canonical`: the display name stored in the database.
- Two rows whose variants have the same match key but different canonicals are a configuration
  error (exit 1) naming both line numbers.
- Initial content: public city-name variants only; never values copied from `contactos/`
  rows other than city names.

## `data/reports/rejects.csv` (generated — contains real contact data)

Encoding `utf-8-sig`, comma-separated, header row, replaced on every successful run. Rows in
source order.

| Column | Content |
|--------|---------|
| `source_file` | file base name |
| `source_sheet` | sheet name |
| `source_row` | 1-based row number |
| `email_raw` | the cell as written |
| `reason` | `empty`, `invalid_format`, `non_ascii_local_part`, `domain_not_found`, `no_mail_server`, `null_mx` |

## `data/reports/review.csv` (generated — contains real contact data)

Encoding `utf-8-sig`, comma-separated, header row, replaced on every successful run. Rows sorted
by `type`, then source order (aggregated rows by `detail`).

| Column | Content |
|--------|---------|
| `type` | see below |
| `source_file` | file base name, empty for aggregated rows |
| `source_sheet` | sheet name, empty for aggregated rows |
| `source_row` | row number, empty for aggregated rows |
| `detail` | value needing review (see below) |
| `count` | 1, or rows affected for aggregated types |

| Type | Detail | Aggregated |
|------|--------|------------|
| `company_contains_at` | company cell as written | no |
| `multi_address_cell` | email cell as written | no |
| `invalid_token_in_multi_cell` | the invalid token | no |
| `city_not_in_mapping` | first spelling seen | yes, per match key |
| `unverified_domain` | normalized address | no |
| `stored_domain_now_fails` | normalized address and status, `address (status)` | no |

## `data/b2b.sqlite3` (generated — contains real contact data)

Schema and rules in [../data-model.md](../data-model.md). Other specs read it and add columns
or tables only through migrations that raise `PRAGMA user_version`.
