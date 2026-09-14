# Quickstart: First Outreach Email and Sending

**Feature**: 002-first-email-send

Validation guide. Commands run from the project root. Follow the steps in order — this is the
rollout order required by Constitution principle V.

## Prerequisites

- Implementation of spec 002 authorized by the user; spec 001 database at `data/b2b.sqlite3`.
- No new packages (`requirements.txt` unchanged).
- `.env` has the SES SMTP settings; add `TEST_RECIPIENTS` (your own addresses on at least two
  different providers, e.g. the Google Workspace mailbox and a personal Gmail or Outlook).
- DMARC: publish `_dmarc.dvconsultores.com TXT "v=DMARC1; p=none"` (manual DNS change), or plan
  to use `--force-no-dmarc` for the first batch.

## 1. Automated tests (synthetic data, no network)

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass, including spec 001's. Coverage per requirement:

| Scenario | Proves |
|----------|--------|
| Template or phrase with `https://`, `www.`, `ejemplo.com`, `<b>` → exit 1 | FR-002 |
| Name/city/company present, missing, all-caps company with `C.A.`, honorific before name | FR-003, US1-2/3/4 |
| Rendered body always ends with the opt-out sentence | FR-004 |
| Launch-price end date in the past → exit 1 in every mode; passes mid-run → stop | FR-005, SC-008 |
| Preview writes the file, leaves `contacts`, `runs`, `send_attempts` untouched, opens no socket | FR-006, US1-1 |
| Test mode sends only synthetic samples to `TEST_RECIPIENTS`, `[PRUEBA] ` subject, no rows written | FR-007, US2 |
| Wrong confirmation text → exit 3, nothing sent | FR-008, US3-1 |
| Eligibility excludes contacted/bounced/responded/opted-out/generic; one per company; 2020 first | FR-009, FR-010, US3-3 |
| Rolling cap, batch limit, window close, jittered intervals with a fake clock | FR-011, SC-003 |
| Pending row committed before the fake SMTP call; crash simulation → `unknown` on restart, never re-sent | FR-012, US3-6, SC-001 |
| Accepted → `times_contacted` 1; 5xx recipient refusal → bounced | FR-013, US3-2/4 |
| Bounce rate above 2% after 20 sends → stop before next email | FR-014, US3-5, SC-004 |
| DMARC missing → exit 3; with `--force-no-dmarc` → continues and `runs.forced_no_dmarc = 1` | FR-015, US4 |
| Headers: From name, Reply-To sender, single text/plain part, no attachment | FR-016 |
| Summary/stderr contain no synthetic address, name, company or credential | FR-017 |
| Second batch refused until an `inbox` run finishes after the first | FR-018 |
| Second concurrent send run → exit 3 | lock |
| SES 454 / 554 not verified / auth failure stop the run without marking contacts bounced | R4 |

## 2. Preview (no email sent)

```bash
.venv/bin/python -m b2b.send_first_email
```

Expected: exit 0, `send_first_email: preview done`, `selected: 100` (or fewer), a file in
`data/previews/`. Open it and read at least 10 emails: greeting, company capitalization, city
fallback, no empty placeholders, opt-out sentence last.

## 3. Test send to your own addresses

```bash
.venv/bin/python -m b2b.send_first_email --mode test
```

Expected: exit 0, `test emails sent: 3`. In each test mailbox confirm: arrives in the inbox (not
spam) — SC-005 — subject starts with `[PRUEBA] `, accents correct, From shows the sender name,
replying goes to the sender address. Check "Show original" in Gmail for `dkim=pass` and
`dmarc=pass` (or `dmarc=none` if not yet published).

## 4. First production batch (needs explicit user authorization for this run)

Run inside `tmux` — 100 emails at 20 per hour take about 5 hours.

```bash
.venv/bin/python -m b2b.send_first_email --mode send            # or add --force-no-dmarc
```

Expected: the confirmation block; typing the campaign name starts sending; summary at the end
with `stop reason: batch_complete`, exit 0.

Database checks (counts only):

```bash
.venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("data/b2b.sqlite3")
q = lambda s: c.execute(s).fetchall()
print("schema:", q("PRAGMA user_version"))
print("attempts by status:", q("SELECT status, COUNT(*) FROM send_attempts GROUP BY status"))
print("contacted:", q("SELECT COUNT(*) FROM contacts WHERE times_contacted > 0"))
print("companies emailed twice in campaign:", q("SELECT COUNT(*) FROM (SELECT c.company_key FROM send_attempts a JOIN contacts c ON c.id = a.contact_id WHERE a.status = 'accepted' GROUP BY a.campaign, c.company_key HAVING COUNT(*) > 1)"))
print("runs:", q("SELECT kind, stop_reason, forced_no_dmarc FROM runs"))
EOF
```

Expected: schema 2; `contacted` equals accepted attempts; zero companies emailed twice.

## 5. Before the next batch

Running `--mode send` again must refuse with the batch-hold error (exit 3) until the manual inbox check
is recorded: `python -m b2b.mark_inbox_checked` (Docker: `docker compose run --rm b2b-outreach mark-inbox-checked`).
