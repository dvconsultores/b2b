# Implementation Plan: First Outreach Email and Sending

**Branch**: `002-first-email-send` (no git) | **Date**: 2026-09-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-first-email-send/spec.md`

## Summary

A command `python -m b2b.send_first_email` renders the plain-text Spanish first email for
contacts in the spec 001 database and works in three modes: `preview` (default — writes a
local preview file, sends nothing), `test` (sends synthetic samples to the operator's own
addresses) and `send` (production). Production passes a chain of gates — single-run lock,
recovery of interrupted attempts, the batch hold until inbox processing (FR-018), the bounce
threshold, the DMARC preflight (overridable with `--force-no-dmarc`), the send window, and a
typed confirmation — then sends one email at a time through Amazon SES SMTP with a rolling
hourly cap. Every attempt is committed to the database before the SMTP call, so no contact is
ever emailed twice. Schema version 2 adds `runs` and `send_attempts`.

## Technical Context

**Language/Version**: Python 3.13.5 (`.venv/`)

**Primary Dependencies**: standard library `smtplib`, `ssl`, `email`, `tomllib`, `zoneinfo`,
`fcntl`, `random`; existing dnspython 2.8.0 (DMARC/SPF lookup) and python-dotenv 1.2.3 (`.env`)

**Storage**: `data/b2b.sqlite3` migrated to schema version 2; preview files in `data/previews/`

**Testing**: pytest 9.1.1; fake SMTP class, fake clock/sleeper/input, fake resolver; network
blocked by `tests/conftest.py`

**Target Platform**: Linux workstation, run by the operator (production runs last hours; run
inside `tmux` or `screen`)

**Project Type**: Single-project CLI tool (extends spec 001's `b2b/` package)

**Performance Goals**: preview of the whole database < 1 minute (SC-007); production pace
governed by the hourly cap (default 20/hour → a 100-email batch takes about 5 hours)

**Constraints**: at most one email per contact per campaign step, including after crashes
(SC-001); no URL, HTML or attachment ever sent (SC-002); cap and batch limit never exceeded
(SC-003); no contact values on screen; credentials never printed

**Scale/Scope**: 2,433 contacts (2,396 personal) of which roughly 2,000 companies; first
production batch 100

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Sender Reputation First | Pass | Hourly cap (rolling, stored in the database), batch limit, send window, auto-pause above 2% after 20 sends, batch hold until inbox processing, DMARC preflight (D10, D11). The DMARC override is the spec's explicit operator decision and is recorded per run. |
| II. Never Contact Twice or Unwillingly | Pass | Attempt row committed before each SMTP call; `UNIQUE(contact_id, campaign, step)`; interrupted attempts become `unknown` and block the contact from every first-email campaign; eligibility excludes contacted, bounced, responded and opted-out contacts (D3, D8, D11). |
| III. Plain, Human First Contact | Pass | Plain text only, template and rendered text checked for URLs and HTML, no attachment code path, opt-out sentence appended by the renderer, sender name and address from `.env` (D5, D6, D12). |
| IV. Contact Data Stays Local | Pass | Preview files stay in `data/previews/`; production email goes only to that recipient via SES; test mode uses a synthetic sample, never prospect data; DNS preflight queries only the sender domain; credentials and test recipients live in `.env` (D9, D13, D14, D17). |
| V. Safe by Default | Pass | Default mode `preview`; production needs `--mode send` plus typing the campaign name; order preview → test → send documented in quickstart; counts-only summaries (D9, D10, D15). |
| VI. Simple, Reviewable Steps | Pass | No new third-party dependency; TOML config and a plain-text template the operator edits; preview file readable before sending (D2, D4, D5). |

## Pinned Decisions

- **D1 — Layout**: new modules `b2b/campaign.py` (config), `b2b/template.py` (template
  loading, validation, rendering), `b2b/preflight.py` (DMARC/SPF), `b2b/preview.py` (preview
  file), `b2b/send_report.py` (summary text), `b2b/eligibility.py` (recipient selection),
  `b2b/tracking.py` (runs, attempts, bounce rate, batch hold, lock), `b2b/pacing.py` (window,
  cap, intervals), `b2b/mailer.py` (credentials, message, SMTP, outcome classification),
  `b2b/send_first_email.py` (CLI). `b2b/store.py` gains the v2 migration. Operator files
  `config/campaign.toml` and `config/templates/primer_contacto.txt`. See Project Structure.
- **D2 — Dependencies**: none added. `requirements.txt` unchanged.
- **D3 — Schema v2**: `store.SCHEMA_VERSION = 2`. `ensure_schema` creates v1 then applies
  migrations in order; the v1→v2 migration adds `runs` and `send_attempts` exactly as
  [data-model.md](data-model.md) and sets `user_version = 2`, in one transaction. A database
  at version 1 is migrated by any command that opens it; version > 2 is refused.
- **D4 — Campaign config**: `config/campaign.toml` read with `tomllib`; keys, types, defaults
  and ranges in [contracts/files.md](contracts/files.md). Unknown keys, wrong types or
  out-of-range values → `ConfigError` naming the key. `launch_price_end` is a TOML date.
- **D5 — Template**: `config/templates/primer_contacto.txt`, UTF-8. Line 1 is
  `Asunto: <subject>`, line 2 is blank, the rest is the body, one line per paragraph (no hard
  wrapping). Allowed placeholders: subject `{empresa}`; body `{saludo}`, `{apertura}`,
  `{remitente}`. Any other `{...}` or a stray brace → `ConfigError`. The template, every
  phrase in `[phrases]` and the `[test_sample]` values are rejected (`ConfigError`) when they
  match the link pattern `(?i)(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|ve|co|io|info|biz|app|dev|me)\b)`
  or the HTML pattern `(?i)(</?[a-z][^>]*>|&[a-z]+;)`. The renderer appends a blank line and
  `phrases.opt_out` to every body; the template must not contain the opt-out sentence itself.
- **D6 — Rendering**: `display_company(company)`: empty → `phrases.company_fallback`; if the
  name has letters and none is lowercase, title-case each space-separated word (first letter
  upper, rest lower), keep `de, del, la, las, los, y, e, en` lowercase except first, rewrite
  legal-suffix tokens by their letters-only key (`ca` → `C.A.`, `sa` → `S.A.`, `srl` →
  `S.R.L.`, `cia` → `Cía.`) keeping trailing punctuation, and keep words of ≤ 4 letters with no
  vowel uppercase; otherwise return it unchanged. `first_name(contact_name)`: split on spaces,
  drop tokens whose letters-only casefold is in `ing, lic, licda, dr, dra, sr, sra, srta, abg,
  arq, econ, prof, msc, mba, tsu`; take the first remaining token; empty or containing a digit or
  `@` → no name; all-caps → capitalize. Saludo: `phrases.greeting_with_name` with `{nombre}` or
  `phrases.greeting_without_name`. Apertura: `phrases.opening_with_city` with `{empresa}` and
  `{ciudad}` when city is non-empty, else `phrases.opening_without_city` with `{empresa}`.
  Remitente: `SMTP_FROM_NAME`. A rendered subject or body that matches the D5 link or HTML
  pattern (data such as a company called `Tienda.com`) → the contact is skipped with reason
  `rendered_link`.
- **D7 — Launch-price date**: "today" is the current date in `campaign.timezone`. Preview, test
  and send refuse to start (exit 1) when today > `launch_price_end`; a production loop stops
  (`launch_price_ended`) before the next email once it passes.
- **D8 — Eligibility**: candidates are contacts with `times_contacted = 0`, `bounced = 0`,
  `responded = 0`, `opted_out = 0`, `classification = 'personal'`, no attempt for this
  campaign and step, and no attempt with status `pending` or `unknown` in any campaign.
  Companies are excluded when any contact with the same `company_key` has an attempt in this
  campaign and step with status `accepted`, `pending` or `unknown`. From each remaining
  `company_key` one contact is chosen: highest completeness (non-empty count of company,
  contact_name, city, tax_id, area), then `source_year` descending, then `source_row`
  ascending, then `email` ascending. Chosen contacts are ordered by `source_year` descending
  then `id` ascending; the first `batch_limit` are selected after dropping `rendered_link`
  contacts. Counts: eligible, skipped_same_company, skipped_rendered_link, selected.
- **D9 — Modes**:
  - `preview` (default): D7 check, template/config validation, schema migration if needed,
    selection, render, write `data/previews/<campaign>-<YYYYMMDD-HHMMSS>.txt` (format in
    contracts/files.md); no row written, no SMTP or DNS.
  - `test`: D7 check, validation, `TEST_RECIPIENTS` from `.env` (1–5 valid addresses),
    renders up to `test_sample_count` synthetic variants from `[test_sample]` (full; without
    name; without city), subject prefixed `[PRUEBA] `, sent sequentially round-robin to the test
    recipients through the D12 path; DMARC/SPF status shown but not blocking; no database read
    or write beyond schema migration.
  - `send`: gates D10, then loop D11.
- **D10 — Production gates, in order** (first failure ends the run): (1) exclusive
  `fcntl.flock` on `<db path>.send.lock`, busy → exit 3; (2) config, template, D7, `.env`
  credentials → exit 1; (3) schema v2 and recovery: every `pending` attempt becomes `unknown`
  with `error_kind = 'interrupted'`; (4) batch hold FR-018 (tracking D11 rule) → exit 3;
  (5) campaign bounce rate already above threshold → exit 3; (6) SMTP login check (connect,
  login, quit) → failure exit 1; (7) DMARC preflight: status other than `present` without
  `--force-no-dmarc` → exit 3; (8) send window: now outside → exit 0 with the next opening
  time; (9) selection: zero → exit 0; (10) confirmation prompt showing campaign, step,
  selected count, hourly cap, batch limit, window, DMARC status and force flag, requiring the
  operator to type the campaign name exactly → otherwise exit 3; (11) insert `runs` row
  (`kind = 'send_production'`, `forced_no_dmarc`).
- **D11 — Send loop**: for each selected contact: stop checks in order — launch-price date
  (`launch_price_ended`), campaign bounce rate (`bounce_threshold`), rolling cap (count of
  attempts with `created_at` in the last 3,600 s across all campaigns; at the cap, sleep until
  the oldest leaves the window), send window at the planned send time (`window_closed`).
  Attempt: commit `send_attempts` row `pending`; send (D12); commit outcome — `accepted` →
  `times_contacted = times_contacted + 1`, `last_contacted_at = now`, `message_id`;
  `permanent_rejection` → `bounced = 1`, `bounced_at = now` when `bounced = 0`;
  `temporary_failure` → no contact change; `unknown` → no contact change. Stop rules:
  `unknown` → stop `connection_lost`; stop-class temporary failures (D12) → stop with their
  kind; `temporary_failure_limit` consecutive temporary failures → stop
  `temporary_failures`; selected list exhausted → `batch_complete`. Between attempts sleep
  `3600 / hourly_cap × uniform(0.8, 1.2)` seconds. Finish: set `runs.finished_at` and
  `stop_reason`. Batch hold rule (FR-018): if a `send_production` run exists, the latest one's
  `COALESCE(finished_at, started_at)` must be earlier than the `finished_at` of some
  `runs` row with `kind = 'inbox'`; otherwise refuse. Bounce rate: over attempts of this
  campaign and step with status `accepted` or `permanent_rejection`, the share whose contact has
  `bounced = 1`; evaluated only when that count ≥ `bounce_min_sends`; stop when >
  `bounce_pause_threshold`.
- **D12 — SMTP**: one connection per email (`timeout = 30` s): port 465 → `smtplib.SMTP_SSL`
  with `ssl.create_default_context()`; port 587 → `smtplib.SMTP` + `starttls(context=...)`;
  any other port → `ConfigError`. Message: `EmailMessage(policy=email.policy.SMTP)`;
  `From` = `formataddr((SMTP_FROM_NAME, SENDER_EMAIL))`; `To` = the bare address; `Reply-To` =
  `SENDER_EMAIL`; `Subject`; `Date` = `format_datetime(now)`; `Message-ID` =
  `make_msgid(domain=<sender domain>)`; `set_content(body, subtype="plain", charset="utf-8",
  cte="quoted-printable")`; no other parts or headers. Envelope sender `SENDER_EMAIL`.
  Outcome classification: connect/TLS/login exceptions (`OSError`, `smtplib.SMTPException`
  before `sendmail`) → `temporary_failure` kind `connection_failed` or `authentication_failed`
  (stop-class); `sendmail` returns with no refusal → `accepted`; `SMTPRecipientsRefused` with
  a 5xx code → `permanent_rejection` kind `recipient_refused`, 4xx → `temporary_failure` kind
  `recipient_deferred`; `SMTPSenderRefused` → `temporary_failure` kind `sender_refused`
  (stop-class); `SMTPDataError` 454 → `provider_throttled` (stop-class), 554 whose text
  contains `not verified` → `identity_not_verified` (stop-class), other 5xx →
  `message_rejected` (stop-class), other 4xx → `data_deferred`; `SMTPServerDisconnected`,
  `TimeoutError` or other `OSError` during `sendmail` → `unknown` kind `connection_lost`.
  `quit()` errors after an outcome are ignored. SMTP response text is never stored or printed;
  only the numeric code and the kind.
- **D13 — Credentials and test recipients**: `dotenv_values(<--env path>)` (never exported to
  `os.environ`); required `HOST_EMAIL`, `PORT_EMAIL` (integer), `USER_EMAIL`, `PASS_EMAIL`,
  `SENDER_EMAIL` (valid per spec 001 `emails.validate`), `SMTP_FROM_NAME` (non-empty, no link
  or HTML); test mode also `TEST_RECIPIENTS` (comma-separated, 1–5 valid addresses). Missing or
  invalid → `ConfigError` naming the key only.
- **D14 — Preflight**: sender domain = domain of `SENDER_EMAIL`. DMARC: TXT at
  `_dmarc.<domain>`; any record starting `v=DMARC1` → `present` (policy `p=` value kept),
  NXDOMAIN/NoAnswer or no such record → `missing`, other DNS error → `unverified`. SPF: TXT at
  the domain starting `v=spf1` → `includes_ses` when it contains `include:amazonses.com`, else
  `present_without_ses`; none → `missing`; DNS error → `unverified`. Resolver injectable;
  lifetime 5 s.
- **D15 — Output and exit codes**: counts-only summary and exit codes in
  [contracts/cli.md](contracts/cli.md); errors on stderr prefixed `send_first_email: error:`
  naming the key, file or gate, never contact values, credentials or SMTP response text. No
  log files.
- **D16 — Testability**: `main(argv, *, smtp_factory=None, resolver=None, now=None, sleep=None,
  ask=None, rng=None) -> int` — injected SMTP class factory, DNS resolver, clock returning an
  aware UTC datetime, sleep function, input function and `random.Random`. Tests never open
  sockets (conftest guard) and use synthetic contacts inserted through `store.upsert_contacts`.
- **D17 — Data handling**: preview files contain real contact data and stay in
  `data/previews/` (already under the DeepSeek egress rule). Test emails carry only the
  `[test_sample]` synthetic values. `TEST_RECIPIENTS` lives in `.env`.

## Amendment 2026-09-13 — Unattended Docker runs (spec 003 deferred)

Decided with the operator after implementation: production runs happen in a Docker container on the
server, and automatic inbox processing (spec 003) is dropped for now.

- **D18 — Launch-time confirmation**: `--confirm <campaign>` (send mode only) replaces the typed
  prompt; it must equal `campaign.name`, otherwise exit 3. The confirmation block is still printed to
  the log first (constitution v1.1.0, principle V).
- **D19 — Waiting for the window**: `--wait-for-window` (send mode only): outside the window at start,
  or when the next planned send falls outside it, sleep until `next_window_start` and continue; the
  launch-price, bounce and cap checks are re-evaluated after every wait. Without the flag, D10/D11
  behavior is unchanged.
- **D20 — End-of-run summary email**: `--notify` (send mode only; requires `TEST_RECIPIENTS`): after a
  production run ends (batch complete, guard stop or interruption) the counts-only
  `format_send_summary` text is emailed to each `TEST_RECIPIENTS` address with subject
  `[b2b] <campaign>: <result> (<stop reason>)`. Refusals before a run starts send nothing.
- **D21 — Signals**: in send mode SIGTERM is handled like Ctrl+C (run finished as `interrupted`,
  exit 130), so `docker stop` never leaves a run open.
- **D22 — Manual inbox check**: `python -m b2b.mark_inbox_checked [--db PATH]` inserts a `runs` row
  (`kind = 'inbox'`, `stop_reason = 'manual_check'`), satisfying the FR-018 batch hold.
- **D23 — Container and scripts**: `Dockerfile` (python:3.13-slim + tzdata; code and config only),
  `docker-entrypoint.sh` (`send` → `--mode send --confirm "$CONFIRM_CAMPAIGN" --wait-for-window
  --notify [--force-no-dmarc]`; `preview`; `mark-inbox-checked`), `b2b.yml` compose file in `/opt/b2b` (database in `/opt/b2b/data`, `.env` mounted read-only)
  (`restart: "no"`, Watchtower disabled), `deploy.sh`, `push-db.sh`; runbook in `docs/deployment.md`.

## Project Structure

### Documentation (this feature)

```text
specs/002-first-email-send/
├── spec.md
├── plan.md              # this file
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md           # command, modes, gates, exit codes, summary
│   └── files.md         # campaign.toml, template, preview file, .env keys
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (project root)

```text
b2b/
├── store.py             # + schema v2 migration (D3)
├── campaign.py          # D4
├── template.py          # D5, D6
├── preflight.py         # D14
├── preview.py           # preview file writer (D9)
├── send_report.py       # summary text (D15)
├── eligibility.py       # D8
├── tracking.py          # runs, attempts, recovery, bounce rate, batch hold, lock (D10, D11)
├── pacing.py            # window, rolling cap, intervals (D11)
├── mailer.py            # credentials, message, SMTP outcome (D12, D13)
└── send_first_email.py  # CLI (D9, D10, D11, D16)
config/
├── campaign.toml
└── templates/
    └── primer_contacto.txt
data/previews/           # runtime — REAL CONTACT DATA
tests/
├── test_store.py        # + migration tests
├── test_campaign.py
├── test_template.py
├── test_preflight.py
├── test_preview.py
├── test_send_report.py
├── test_eligibility.py
├── test_tracking.py
├── test_pacing.py
├── test_mailer.py
└── test_send_first_email.py
```

**Structure Decision**: extend the spec 001 package; one module per pinned decision so each
task stays within two files.

## Delegation Notes (for /speckit-tasks)

- Likely DEEPSEEK: `campaign.py`, `template.py`, `preflight.py`, `preview.py`,
  `send_report.py`, `config/templates/primer_contacto.txt`, and their tests — pinned, no
  credentials, no send decisions.
- CLAUDE: `store.py` migration, `tracking.py`, `eligibility.py`, `pacing.py`, `mailer.py`,
  `send_first_email.py`, `config/campaign.toml`, end-to-end tests — the send path, recipient
  selection, throttling and credentials (`.claude/CLAUDE.md` exceptions).

## Post-Design Constitution Re-check

All six gates still pass: the data model enforces one attempt per contact, campaign and step at
the database level (II); contracts forbid links, HTML and attachments and append the opt-out
sentence (III); test mode's synthetic sample keeps prospect data out of test emails (IV); the
CLI defaults to preview and requires a typed confirmation (V). No violations.

## Complexity Tracking

No constitution violations to justify.
