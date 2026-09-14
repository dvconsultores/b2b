# Changelog

## 2026-09-13

- ops: unattended Docker runs and public repository (user request). Spec 003 (automatic inbox
  processing) deleted — inbox is checked manually. `send_first_email` send mode gains
  `--confirm`, `--wait-for-window`, `--notify` and SIGTERM handling; new
  `b2b/mark_inbox_checked.py` releases the batch hold. Added `Dockerfile`,
  `docker-entrypoint.sh`, `docker-compose.yml` (`/opt/b2b`, no restart, Watchtower disabled),
  `.dockerignore`, `.gitignore`, `deploy.sh` (tests → build → image check → push), `push-db.sh`
  (OVERWRITE prompt, running-container and tracking-history guards, server snapshot),
  `docs/deployment.md`. Constitution 1.0.0 → 1.1.0 (launch-time confirmation, public repo,
  one batch per launch). Spec 002 plan D18–D23, spec, contract, data model, research and
  quickstart updated; `.claude/CLAUDE.md` notes git, deployment and new `.env` keys in the
  egress rule. Local image build verified: no `.env`, database or `contactos/` inside.

- ops: second test send (3 synthetic samples, SES accepted) at the user's request; user approved
  the email content ("is perfect") — spec 002 T025 and T026 complete.

- ops: spec 002 real runs authorized by the user. `.env` gained `TEST_RECIPIENTS` (1 address).
  Real preview (T025): exit 0, database migrated to schema v2, 2,396 eligible, 354 skipped same
  company, 2 skipped for a domain in the company name, 100 selected; file
  `data/previews/primer-contacto-2026-20260913-200843.txt`; checks: 0 leftover placeholders,
  0 links/HTML, 100 greetings "Hola," (2020 file has no contact names), 17 with city / 83
  without, 100 end with the opt-out sentence. City presence among the 2,042 chosen contacts is
  1,441; the first 2020 rows are the sparsest (53 of the first 200). Test send (T026): exit 0,
  3 synthetic samples accepted by SES; DMARC missing, SPF present without SES. Awaiting operator
  review of the preview wording and inbox placement.

- feat: implement spec 002 first email and sending (tasks T001, T002, T004–T024). Command
  `.venv/bin/python -m b2b.send_first_email --mode preview|test|send [--force-no-dmarc]`.
  Added `config/campaign.toml`, `config/templates/primer_contacto.txt`; modules
  `b2b/campaign.py`, `template.py`, `preflight.py`, `preview.py`, `send_report.py`,
  `eligibility.py`, `pacing.py`, `tracking.py`, `mailer.py`, `send_first_email.py`;
  `b2b/store.py` schema v2 (`runs`, `send_attempts`, migrated automatically from v1); tests for
  each module plus `tests/test_send_first_email.py`; new fixtures in `tests/conftest.py`
  (fake SMTP, clock, `.env`, campaign files, contacts). 356 tests passing, synthetic data only,
  no network. DeepSeek v4-flash: 8 calls for 6 tasks (2 retries), about $0.0085. Not yet run
  against real data: operator adds `TEST_RECIPIENTS` (T003); real preview, test send, first
  batch and batch-hold check (T025–T030) await authorization.
- docs: spec 002 `contracts/cli.md` — `runs.forced_no_dmarc` is 1 only when DMARC was not
  present; spec 001 `quickstart.md` — schema version becomes 2 once a spec 002 command opens
  the database.

- docs: generate `specs/002-first-email-send/tasks.md` — 30 tasks (setup, foundational, US1
  preview, US2 test send, US3 production, US4 DMARC gate, polish/operations) with pinned module
  interfaces; 6 DEEPSEEK, 21 CLAUDE, 3 OPERATOR.

- docs: plan spec 002 (`specs/002-first-email-send/plan.md`, `research.md`, `data-model.md`,
  `contracts/cli.md`, `contracts/files.md`, `quickstart.md`) — `b2b.send_first_email` with
  preview/test/send modes, schema v2 (`runs`, `send_attempts`), at-most-once attempts, rolling
  hourly cap, DMARC preflight with force option, batch hold, SES SMTP outcome classification,
  `config/campaign.toml` and plain-text template; `.env` gains `TEST_RECIPIENTS`. Active
  feature switched to 002; `.claude/CLAUDE.md` Stack section notes the planned command.

- data: re-run safety check (spec 001 T028, authorized by the user). Real database re-run:
  exit 0, 0 existing contacts updated, 2,429 unchanged, 4 new (3 previously unverified domains
  answered, 1 previously "domain not found" now accepts mail) → 2,433 contacts; no stored
  contact's domain failed; unverified 15 → 12. Strict SC-004 identity did not hold for this
  run only because DNS answers changed between runs. Copy check: tracking and timestamps on
  5 contacts unchanged after an import, only those 5 non-default; copy and its reports
  deleted.

- data: first real import (spec 001 T027, authorized by the user) — exit 0 in 17 s. Rows read
  1,620 (2020) + 1,287 (2009); sheets `SQL`, `14-100` skipped. Stored 2,429 contacts
  (1,425 from 2020, 1,004 from 2009; 2,392 personal, 37 generic; 2,074 company keys; 622
  without city). Rejected 367: format 30 (26 invalid, 4 non-ASCII local part), domain 337
  (272 not found, 37 null MX, 28 no mail server — 76 in 2020, 261 in 2009). Merged 96
  duplicates (42 with conflicting company/city). Review items 111: 94 unmapped city spellings
  covering 347 contacts, 15 unverified domains, 2 company cells with `@`. Checks: schema v1,
  0 duplicate emails, 0 non-default tracking values.
- docs: correct Year Book data rows 1,281 → 1,287 (1,281 is its unique-address count) in
  spec 001 `spec.md`, `plan.md`, `research.md`, `quickstart.md`, `tasks.md`.

- feat: implement spec 001 clean contact database (tasks T001–T026, T030). Command
  `.venv/bin/python -m b2b.import_contacts`. Added `requirements.txt`, `requirements-dev.txt`;
  package `b2b/` (`__init__`, `sources`, `emails`, `domains`, `companies`, `cities`,
  `classify`, `merge`, `store`, `reports`, `import_contacts`); `config/role_words.txt`,
  `config/cities.csv`; `tests/` (conftest + 10 test modules, 168 tests passing on synthetic
  data, network blocked). Updated `.claude/CLAUDE.md` Stack section. DeepSeek v4-flash: 13
  calls for 11 tasks (2 test retries), about $0.011 total. Real import (T027–T029) not run yet
  — awaiting user authorization.

- docs: generate `specs/001-clean-contact-list/tasks.md` — 30 tasks (setup, foundational,
  US1–US4, polish) with pinned module interfaces and DEEPSEEK/CLAUDE/OPERATOR classification.

- docs: plan spec 001 (`specs/001-clean-contact-list/plan.md`, `research.md`,
  `data-model.md`, `contracts/`, `quickstart.md`) — xlrd/openpyxl readers, dnspython domain
  check, SQLite schema v1 with tracking fields, CSV reports; `data/` added to the DeepSeek
  egress rule in `.claude/CLAUDE.md` and `deepseek-executor`.

- docs: ratify constitution v1.0.0 (`.specify/memory/constitution.md`) from
  `docs/plan.md` — sender reputation, no duplicate/unwanted contact, plain first email,
  contact data stays local, safe by default, simple reviewable steps.
- docs: add spec `specs/001-clean-contact-list/spec.md` (Parts A–D of `docs/plan.md`:
  load, clean, verify domains, dedupe, classify) with quality checklist; clarified.
- docs: amend spec 001 to a SQLite database of valid-to-send contacts with tracking fields
  (times contacted, last contacted, bounced, responded, opted out); re-runs keep tracking.
- docs: add spec `specs/002-first-email-send/spec.md` (plain-text Spanish first email with
  reply CTA and introductory-price end date, one contact per company, deliverability
  preflight, dry run, test sends, throttled SES sending); clarified.
- docs: revise spec 002 — urgency "launch price all year, best price–quality" (no amount),
  SES readiness confirmed, DMARC block overridable with a force option, further batches held
  until spec 003 has run (FR-018); spec 003 records run completion (FR-013).
- docs: add spec `specs/003-inbox-bounces-replies/spec.md` (Google Workspace mailbox via app
  password: record bounces, complaints and opt-outs; forward real replies to a person).

- docs: set up Claude (thinker) + DeepSeek (executor) orchestration —
  `.claude/CLAUDE.md`, `.claude/agents/deepseek-executor.md`,
  `.claude/agents/spec-kit-coordinator.md`, `.claude/settings.json`,
  `scripts/set_deepseek_key.py`, Spec Kit `claude` integration. See
  `docs/ai-agent-orchestration.md`.
