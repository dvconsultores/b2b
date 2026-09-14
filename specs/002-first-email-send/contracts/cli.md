# Contract: `send_first_email` command

**Feature**: 002-first-email-send

## Invocation

```text
.venv/bin/python -m b2b.send_first_email [options]
```

| Option | Default | Meaning |
|--------|---------|---------|
| `--mode {preview,test,send}` | `preview` | preview writes a file only; test emails synthetic samples to `TEST_RECIPIENTS`; send is production |
| `--config PATH` | `config/campaign.toml` | campaign settings (template path is inside) |
| `--db PATH` | `data/b2b.sqlite3` | contact database (migrated to schema v2 if at v1) |
| `--env PATH` | `.env` | credentials and `TEST_RECIPIENTS` |
| `--previews-dir PATH` | `data/previews` | where preview files are written |
| `--force-no-dmarc` | off | `send` only: continue when DMARC is not `present`; `runs.forced_no_dmarc` is set to 1 only when DMARC was not present |
| `--confirm CAMPAIGN` | none | `send` only: confirm at launch instead of typing; must equal the campaign name (exit 3 otherwise) |
| `--wait-for-window` | off | `send` only: sleep until the send window opens (at start and mid-batch) instead of stopping |
| `--notify` | off | `send` only: email the counts-only summary to `TEST_RECIPIENTS` when the run ends |
| `--ses-guard` | off | `send` only (spec 003): sync bounces from the SES API before starting and before every email; refuse / stop on the real SES bounce rate; needs the `AWS_*` keys |

Send-only options (`--force-no-dmarc`, `--confirm`, `--wait-for-window`, `--notify`, `--ses-guard`) with
another mode → exit 1. The typed confirmation can only be replaced by `--confirm` with the exact campaign name.

Python entry point for tests:
`b2b.send_first_email.main(argv, *, smtp_factory=None, resolver=None, now=None, sleep=None, ask=None, rng=None, ses_clients=None) -> int`.

## Confirmation (send mode)

Printed to stdout, then the operator types at the prompt:

```text
campaign:        primer-contacto-2026 (step 1)
recipients:      <n>
hourly cap:      <n> per hour
batch limit:     <n>
send window:     mon–fri 08:00–17:00 America/Caracas
DMARC:           present (p=none) | missing | unverified
SPF:             includes_ses | present_without_ses | missing | unverified
forced no DMARC: yes | no
Type the campaign name to start sending:
```

Anything other than the exact campaign name → exit 3, nothing sent.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | finished: preview written, test emails sent, batch complete, nothing eligible, or started outside the send window |
| 1 | configuration or input error: config, template, `.env` key, launch-price date passed, SMTP login check failed, `--force-no-dmarc` outside send mode |
| 2 | database error or schema newer than 2 |
| 3 | refused by a gate before any email: another send run active, batch hold, bounce rate already above threshold, DMARC not present without force, confirmation not given |
| 4 | production run stopped by a guard after starting: `launch_price_ended`, `bounce_threshold`, `window_closed`, `temporary_failures`, `connection_lost`, `ses_bounce_rate`, `ses_check_failed` or a stop-class error kind |
| 130 | interrupted (Ctrl+C); the in-flight attempt, if any, is resolved as `unknown` at the next production start |

## Standard output — summary

Counts only. Each value line is `"  " + f"{label + ':':<26}" + value`.

```text
send_first_email: <mode> <result>
campaign: <name> (step <n>)
  eligible contacts:        <n>
  skipped same company:     <n>
  skipped rendered link:    <n>
  selected:                 <n>
  previewed:                <n>
  test emails sent:         <n>
  accepted:                 <n>
  permanent rejections:     <n>
  temporary failures:       <n>
  unknown outcome:          <n>
  campaign bounce rate:     <x.x>% (<bounced> of <sent>)
  DMARC:                    <status>
  SPF:                      <status>
  forced no DMARC:          yes | no
  stop reason:              <reason or ->
  next window opens:        <YYYY-MM-DD HH:MM zone or ->
preview: <path or ->
```

`<result>` is `done`, `nothing_to_send`, `outside_window`, `refused` or `stopped`. Lines that do
not apply to the mode show `0` or `-`; all lines are always present. Preview and test mode show
`DMARC`/`SPF` as `-` when not checked (preview never checks DNS).

## Standard error

One line per problem, prefixed `send_first_email: error:`, naming the key, file, gate or stop
reason. Never includes addresses, names, company names, credentials or SMTP response text.

Examples:

```text
send_first_email: error: config/campaign.toml: launch_price_end 2026-12-31 has passed
send_first_email: error: config/templates/primer_contacto.txt: link or domain not allowed in template
send_first_email: error: .env: missing TEST_RECIPIENTS
send_first_email: error: batch hold: check the inbox (bounces, replies, opt-outs) and run python -m b2b.mark_inbox_checked before the next production batch
send_first_email: error: DMARC not present for sender domain; publish it or pass --force-no-dmarc
send_first_email: error: another send run is active
```

## `mark_inbox_checked` command

```text
.venv/bin/python -m b2b.mark_inbox_checked [--db PATH]      # default data/b2b.sqlite3
```

Records a manual inbox check (`runs` row, `kind = 'inbox'`), releasing the batch hold. Prints
`mark_inbox_checked: recorded manual inbox check at <UTC timestamp>`. Exit 0, or 2 when the database
is missing or its schema is newer than supported.

## Docker entrypoint (`docker-entrypoint.sh`)

| Command | Runs |
|---------|------|
| `send` (default) | `send_first_email --mode send --db /app/data/b2b.sqlite3 --env "$ENV_FILE"` (default `/app/data/.env`; `b2b.yml` sets `/app/.env`) `--confirm "$CONFIRM_CAMPAIGN" --wait-for-window --notify --ses-guard` plus `--force-no-dmarc` when `FORCE_NO_DMARC=1`; exit 3 when `CONFIRM_CAMPAIGN` is empty |
| `preview` | import on start (below), then preview mode, previews in `/app/data/previews` |
| `import` | only `import_contacts --clients /app/contactos/$CLIENTS_FILE --yearbook /app/contactos/$YEARBOOK_FILE --db /app/data/b2b.sqlite3 --reports-dir /app/data/reports --config-dir /app/config` |
| `mark-inbox-checked` | `mark_inbox_checked --db /app/data/b2b.sqlite3` |
| `sync-bounces [--dry-run]` | `sync_bounces --db /app/data/b2b.sqlite3 --env "$ENV_FILE"` (spec 003) |
| anything else | executed as given |

Import on start: when `IMPORT_ON_START=1` (default), `send` and `preview` run the `import` step first.
Both files present → import; a non-zero exit stops the container with that code and nothing is sent.
Files missing but the database exists → import skipped (logged). Files and database missing → exit 1.
