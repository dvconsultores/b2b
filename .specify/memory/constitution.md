<!--
Sync Impact Report
- Version change: 1.3.0 → 1.4.0 (2026-09-14, MINOR)
  - I. Sender Reputation First: a campaign may continue batch after batch in one launch while
    the bounce rate, checked before every email, stays under the pause threshold.
  - Operational Constraints: unattended runs send one batch per launch, or consecutive batches
    when the campaign sets `continuous = true` (spec 005). Requested by the user.
  - Templates: no template changes needed.
- Previous: 1.2.0 → 1.3.0 (2026-09-14, MINOR)
  - IV. Contact Data Stays Local: email addresses alone (no other field) may be uploaded by the
    operator to the email verification service approved in spec 004 (NeverBounce or ZeroBounce)
    to check that mailboxes exist before sending. Requested by the user after the first batch
    bounced at 18%.
  - Templates: no template changes needed.
- Previous: 1.1.0 → 1.2.0 (2026-09-13, MINOR)
  - IV. Contact Data Stays Local: contact data may also be stored and processed on the
    operator's own server (spreadsheets, database) for unattended runs.
  - Templates: no template changes needed.
- Previous: 1.0.0 → 1.1.0 (2026-09-13, MINOR)
  - V. Safe by Default: the campaign-name confirmation may be supplied at launch for unattended
    (Docker) runs; the confirmation details are then written to the run log.
  - Operational Constraints: public git repository (secrets and contact data never committed);
    unattended runs send one batch per launch and stop.
  - Templates: no template changes needed.
- Previous: template (unversioned) → 1.0.0 (initial ratification)
- Principles added: I. Sender Reputation First; II. Never Contact Twice or Unwillingly;
  III. Plain, Human First Contact; IV. Contact Data Stays Local; V. Safe by Default;
  VI. Simple, Reviewable Steps
- Sections added: Operational Constraints; Development Workflow; Governance
- Sections removed: none
- Templates:
  ✅ .specify/templates/plan-template.md — "Constitution Check" derives gates from this file; no edit needed
  ✅ .specify/templates/spec-template.md — no mandatory sections added or removed; no edit needed
  ✅ .specify/templates/tasks-template.md — generic; no principle-specific task types required
  ✅ .claude/CLAUDE.md — already consistent (egress rule, send path Claude-only, dry run, no git)
- Sources: docs/plan.md (strategy), .claude/CLAUDE.md (workflow)
- Deferred TODOs: none
-->

# b2b Outreach Constitution

## Core Principles

### I. Sender Reputation First (NON-NEGOTIABLE)

- No address receives a production email unless it passed the list-quality checks of an
  implemented spec.
- Sending MUST be throttled by a configured per-hour cap. The whole list is never sent at
  once; each campaign starts with a small batch (on the order of 100 addresses). A campaign
  may continue batch after batch in one launch only while its bounce rate, checked before
  every email, stays under the pause threshold.
- Bounce rate MUST be measured per campaign, and sending MUST pause automatically when it
  exceeds the pause threshold (default 2%). Resuming requires a human decision.

Rationale: the email provider (Amazon SES) suspends accounts with high bounce rates. A
suspended sender ends the whole outreach effort; a smaller list costs little.

### II. Never Contact Twice or Unwillingly

- Every send attempt MUST be recorded in the local tracker, and the tracker MUST be checked
  before every send. The same address never receives the same campaign step twice.
- An opt-out (any reply asking to stop) MUST put the address on the suppression list
  immediately and permanently. Suppressed addresses are excluded from every future campaign
  and export.

Rationale: duplicate or unwanted emails generate spam complaints, which damage reputation
faster than bounces.

### III. Plain, Human First Contact

- The first email MUST be plain text: no HTML, images, links, tracking pixels or attachments.
- Attachments are never sent at any step.
- A link to the landing page is sent only after the prospect replies.
- Every email MUST identify the real sender and MUST NOT use misleading subject lines.

Rationale: plain personal messages reach the inbox and get replies; designed emails are
filtered as bulk marketing (docs/plan.md §2).

### IV. Contact Data Stays Local

- `contactos/` and every file derived from it are real personal data. They are processed only on
  this machine and on the operator's own server (copied there over SSH, with restricted file
  permissions), and otherwise leave them only as an individual email to that recipient through
  the configured email provider, or as permitted in the next two rules.
- Contact data MUST NOT be sent to AI providers or other third-party services unless a spec
  explicitly approves a named service and purpose.
- Email verification (spec 004): the operator may upload a file of email addresses only — no
  names, companies, cities or other fields — to NeverBounce or ZeroBounce to check that the
  mailboxes exist before any campaign sends to them. The export and results files stay under
  `data/` with owner-only permissions.
- Code, tests, fixtures, docs and specs contain only column headers, aggregate counts and
  synthetic data (for example `ana@example.com`).
- Credentials live only in `.env` and are never printed, logged or copied elsewhere.
- Only the fields a spec needs are carried forward from the sources (data minimization).

Rationale: the list was collected for business contact; exposing it harms the people in it
and the sender's credibility.

### V. Safe by Default

- Any command that can send email MUST default to a dry run. Real sending requires an
  explicit option plus a confirmation of the exact campaign name: typed after the command shows
  the campaign, recipient count and throttle, or, for unattended runs, supplied at launch — in
  which case the same details are written to the run log before the first email.
- Rollout follows docs/plan.md §6 Part H: clean → classify → tracker → dry run → test sends to
  own addresses → throttled production.
- Every run prints a summary of counts (never contact values).

Rationale: a mistaken send cannot be recalled.

### VI. Simple, Reviewable Steps

- Small Python 3 scripts, standard library first. Every third-party dependency is pinned in
  `requirements.txt` and justified in the feature's `plan.md`.
- Each stage reads files and writes a file a person can open and review before the next stage
  runs. Source files are read-only and never modified in place.
- Local files (CSV or SQLite) are the storage; no servers or hosted databases unless a spec
  justifies them.

Rationale: a one-person outreach tool has to be understandable and checkable at a glance.

## Operational Constraints

- Email provider: Amazon SES through its SMTP interface; connection settings in `.env`
  (`HOST_EMAIL`, `PORT_EMAIL`, `USER_EMAIL`, `PASS_EMAIL`, `SENDER_EMAIL`, `SMTP_FROM_NAME`).
- Source data: `contactos/ClientesFebrero2020.xls` and `contactos/Year Book 2009.xlsx`.
- Runtime: Python 3.13 in `.venv/`.
- Version control: public GitHub repository; `.env`, `contactos/` and `data/` are never
  committed or built into images. Every change also gets an entry in `docs/CHANGELOG.md`.
- Unattended production runs use the Docker image: one batch per launch (or consecutive batches
  when the campaign sets `continuous = true`, until the list is exhausted or a guard stops the
  run), then the container stops and emails a counts-only summary to the operator.

## Development Workflow

- Work follows the Spec Kit loop in `.claude/CLAUDE.md`. Code is written only for a spec the
  user has explicitly authorized for implementation.
- Tests use pytest with synthetic fixtures and a mocked SMTP client. No test reads
  `contactos/` or `.env`, or opens a network connection.
- Every `plan.md` Constitution Check evaluates principles I–VI; any violation is justified in
  Complexity Tracking or the plan is revised.
- Credentials, the send path, suppression and contact-selection rules are implemented by
  Claude, never delegated (see `.claude/CLAUDE.md`).

## Governance

- This constitution supersedes other project documents. `docs/plan.md` is strategy input;
  where it conflicts with this file, this file wins and the conflict is reported.
- Amendments are made only at the user's request, with a Sync Impact Report and a
  `docs/CHANGELOG.md` entry.
- Versioning: MAJOR for removed or redefined principles, MINOR for added principles or
  sections, PATCH for clarifications.
- Compliance is checked in every plan's Constitution Check and in the audit of every task.

**Version**: 1.4.0 | **Ratified**: 2026-09-13 | **Last Amended**: 2026-09-14
