# b2b — Agent Orchestration Rules

## Project ground rules (read first)

- **Constitution:** `.specify/memory/constitution.md` is the source of truth.
  Until it is ratified with `/speckit-constitution`, it is still the Spec Kit
  template: run that first and do not plan features against a placeholder.
- **Implementation gate:** code changes happen only for a spec the user has
  explicitly authorized for implementation. Without that authorization, stop
  after planning/analysis.
- **Stack:** Python 3.13 scripts for B2B outreach. Spec 001 added the `b2b/` package
  (xlrd, openpyxl, dnspython, SQLite) and the command
  `.venv/bin/python -m b2b.import_contacts`; layout and interfaces are pinned in
  `specs/001-clean-contact-list/plan.md` and `tasks.md`.
  Spec 002 adds `.venv/bin/python -m b2b.send_first_email` (modes preview/test/send),
  schema v2 (`runs`, `send_attempts`), `config/campaign.toml`,
  `config/templates/primer_contacto.txt`, previews in `data/previews/`, and the `.env` key
  `TEST_RECIPIENTS`. Production sending is always a user-authorized run.
  - Input data: `contactos/ClientesFebrero2020.xls`, `contactos/Year Book 2009.xlsx`
    — **real client contact data**.
  - SMTP settings in `.env`: `HOST_EMAIL`, `PORT_EMAIL`, `USER_EMAIL`,
    `PASS_EMAIL`, `SENDER_EMAIL`, `SMTP_FROM_NAME`.
  - Dependencies go in `requirements.txt` (dev: `requirements-dev.txt`); virtualenv at `.venv/`.
  - Package `b2b/`, editable settings in `config/`, generated database and reports in `data/`
    (`data/b2b.sqlite3`, `data/reports/`) — **real contact data** (spec 001 plan).
- **Docs:** `docs/CHANGELOG.md`, per-feature `specs/<NNN>/`. Orchestration
  setup: `docs/ai-agent-orchestration.md`.
- **Version control:** public GitHub repository `dvconsultores/b2b`. Never commit
  or build into images `.env`, `contactos/`, `data/` or any database file (see
  `.gitignore`, `.dockerignore`). Commits: `type: short description` (`feat:`,
  `fix:`, `docs:`, `ops:`); stage only the task's files; list every changed file
  in the report and add an entry to `docs/CHANGELOG.md`.
- **Deployment:** the container imports `contactos/` into the database on every start
  (`IMPORT_ON_START=1`), then sends one batch. `./push-contactos.sh` uploads the spreadsheets
  to `/opt/b2b/contactos`; `.env.example` lists every key. `./deploy.sh` (tests, build, push image), `./push-db.sh` (upload
  the tracker DB to `/opt/b2b/data`), server compose file `b2b.yml`; see
  `docs/deployment.md`. Spec 003 (automatic inbox processing) was dropped for now:
  the operator checks the inbox by hand and runs `python -m b2b.mark_inbox_checked`.

## Role Assignment (Non-Negotiable)

| Role | Agent | Responsibility |
|------|-------|----------------|
| **Thinker** | Claude (this agent) | Architecture, specs, planning, task decomposition, auditing, testing, applying approved edits |
| **Spec owner** (optional) | `spec-kit-coordinator` subagent | Runs Spec Kit phases, maintains spec/plan/tasks, classifies tasks |
| **Executor** | DeepSeek via `deepseek-executor` subagent | Bounded implementation: proposes file edits for one task |

Claude does not write mechanical task code itself; it applies DeepSeek's
proposed edits after auditing them. DeepSeek never makes architectural decisions.

## Spec Kit in Claude Code

Spec Kit is installed for **Claude** only. Skills live in
`.claude/skills/speckit-*`, invoked as `/speckit-<phase>` (hyphen) —
`/speckit-constitution`, `/speckit-specify`, `/speckit-clarify`, `/speckit-plan`,
`/speckit-tasks`, `/speckit-analyze`, `/speckit-converge`. They use
`.specify/scripts/bash/`.

In this file, "run `plan`" means the `/speckit-plan` skill (or delegate to
`spec-kit-coordinator`). Feature numbering is sequential: no specs exist yet, so
the first is `001`. Never edit generated skill files by hand — refresh with
`specify integration upgrade claude`.

## The Loop

### 1. ANALYZE (Claude)
- Read the current state of the relevant scripts and related specs. Code wins
  over docs; record INCONSISTENCY DETECTED.
- To learn the spreadsheet layout, Claude inspects `contactos/` itself (column
  headers, types, row counts). Only headers and synthetic rows ever go into a
  spec, plan or delegation.
- Update the constitution only if the user asks.
- `specify` → define what is being built.
- `clarify` → ask the user the open questions before planning.

### 2. PLAN (Claude)
- `plan` with explicit, numbered, pinned decisions.
- `tasks` → atomic work items with exact paths and a **DoD** (definition of done).
- Classify each task DEEPSEEK / CLAUDE (criteria below).
- **Gate:** any ambiguous task is split or clarified before delegation.
- **Gate:** the user authorizes implementation of this spec.

### 3. EXECUTE (DeepSeek via subagent)
- One `deepseek-executor` invocation per task (use the Delegation Prompt Format).
- Independent `[P]` tasks may be delegated in parallel.
- The subagent returns DeepSeek's raw output plus usage and the context it sent.

### 4. AUDIT (Claude)
- Read the proposed edits against `spec.md` and `plan.md`, line by line.
- Run the Audit Checklist.
- **Pass:** apply the SEARCH/REPLACE blocks exactly as written. A SEARCH block
  that does not match the file is a rejection, not something to hand-fix.
- **Fail:** do not fix silently. Re-delegate with `RETRY:` = previous output +
  the specific rejection reason.

### 5. TEST (Claude)
- `.venv/bin/python -m pytest -q` (or the test files named in `plan.md`). Installing
  new packages into `.venv` needs the authorizing plan. Send-path tests use the fake
  SMTP, clock, resolver and `.env` fixtures in `tests/conftest.py`.
- Tests use synthetic fixtures and a mocked `smtplib`; they never read
  `contactos/` or `.env` and never open a network connection.
- **Never send real email to "try" a change.** Running any script that can
  connect to SMTP with the real `.env`, or that reads `contactos/` to build a
  recipient list, requires explicit user authorization for that specific run
  (prefer its dry-run mode when the plan defines one).
- On failure: find the root cause, re-delegate with the test output in `RETRY:`,
  re-audit on return. Do not patch DeepSeek's code directly.
- **Retry cap:** after 2 failed re-delegations of the same task, stop and ask
  the user: re-split the task, switch to `MODEL: pro`, or let Claude implement it.
- A task is complete only when tests pass AND the audit is clean. Mark it `[x]`
  in `tasks.md`.

### 6. CONVERGE (Claude)
- `converge` to assess remaining work.
- Add the change to `docs/CHANGELOG.md`; update `docs/` when behavior, CLI
  usage or architecture changed.

## When Claude Implements Directly (Exceptions)

Claude bypasses the executor ONLY for:
- **SMTP credentials and connection:** loading `.env`, TLS/SSL mode, login,
  anything that handles `PASS_EMAIL` or `USER_EMAIL`.
- **The send path:** recipient selection, the bulk-send loop, throttling and
  rate limits, retry-on-failure (duplicate-send risk), resume after a crash,
  dry-run and confirmation gates.
- **Consent and data protection:** opt-out/unsubscribe handling, suppression
  lists, retention or deletion of contact data.
- **Contact data rules:** deduplication, merging and filtering that decide who
  gets contacted — unless pinned verbatim in `plan.md`.
- Architectural decisions that require reasoning about tradeoffs.
- Debugging where the root cause is unknown.
- Cross-cutting refactors touching > 5 interdependent files.
- Anything where the spec is still being discovered.
- Target files that contain secrets or real contact data.

Typically delegable: email subject/body templates and rendering, CLI argument
parsing, spreadsheet column mapping and normalization helpers pinned in
`plan.md` (email/phone/name cleanup), summary and log formatting, and tests with
synthetic fixtures for behavior already pinned in `plan.md`.

If unsure whether a task qualifies, **ask the user** before delegating or implementing.

## Data Egress Rule

DeepSeek is an external provider. Never send it any `.env*` file, `*.log`, or
values of `HOST_EMAIL`, `PORT_EMAIL`, `USER_EMAIL`, `PASS_EMAIL`, `SENDER_EMAIL`,
`SMTP_FROM_NAME`, `TEST_RECIPIENTS`, `DOCKER_USERNAME`, `DOCKER_PASSWORD`, `SRVUSER`,
`SRVPASS`, `SRVHOST`. Never send real contact data: rows or cells from
`contactos/*.xls` / `*.xlsx` or any CSV/JSON exported from them, anything under
`data/` (the contact database and its reports), send/bounce reports, or real names, emails, phone numbers, addresses or company names of
clients. Column headers and synthetic sample rows are allowed. The executor
enforces this; Claude must not override it.

## Delegation Prompt Format

```
TASK:        <task ID> in specs/<feature>/tasks.md
TARGET:      <file paths to create or modify>
CONSTRAINTS: <explicit rules from plan.md / constitution.md>
DONE WHEN:   <acceptance criteria — the task's DoD>
MODEL:       flash | pro          (optional, default flash)
THINKING:    off | on             (optional, default off)
RETRY:       <previous output + rejection reason / test output>   (retries only)
```

Use `pro` for multi-branch logic or large new files; `THINKING: on` only for
genuinely tricky logic (it can hit the MCP timeout).

## Audit Checklist

Every DeepSeek output must pass all of these before it is applied:

- [ ] Matches `spec.md` requirements and `plan.md` decisions (no more, no less)
- [ ] Minimum modification: no unrelated renames, reformatting, style or behavior changes
- [ ] No invented files, functions, env keys, CLI flags or spreadsheet columns
- [ ] No credentials, real email addresses or contact data in code, tests or fixtures
- [ ] Does not touch SMTP credentials/connection, the send path, consent handling or contact selection rules
- [ ] No code path can send email outside the flow `plan.md` defines (no stray `sendmail`, no network in tests)
- [ ] Error handling covers the paths named in the spec
- [ ] No new dependencies without a `plan.md` entry
- [ ] `QUESTIONS` section is "none" (otherwise resolve, then re-delegate)
- [ ] Diff is reviewable — a 500-line rewrite for a 10-line task is rejected and re-delegated with tighter scope
- [ ] Tests pass

## Reporting

After each task, report to the user:

```
[ANALYZE] <what was found>
[PLAN]    <what was decided>
[EXECUTE] Task <id> → DeepSeek <model> (<in>/<out> tokens, $<cost>)
[AUDIT]   <pass | fail + reason>
[TEST]    <suite + result>
[FILES]   <every file changed>
[STATUS]  <complete | blocked | needs input>
```
