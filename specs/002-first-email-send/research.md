# Research: First Outreach Email and Sending

**Feature**: 002-first-email-send | **Date**: 2026-09-13

Context: `.env` points to the Amazon SES SMTP endpoint in `us-east-2`, port 465, with an SES SMTP
username; the sender domain's mailbox is on Google Workspace; DKIM, production access and bounce
notices to the sender are confirmed by the operator; DMARC is missing and SPF does not include SES.
The database holds 2,433 contacts after spec 001.

## R1 — SMTP interface and port

- **Decision**: `smtplib.SMTP_SSL` on port 465 (implicit TLS) with `ssl.create_default_context()`;
  port 587 supported with STARTTLS; any other port refused.
- **Rationale**: matches `.env` (465); the standard library covers SMTP fully; certificate
  verification stays on by default.
- **Alternatives considered**: SES HTTPS API via boto3 (needs AWS API credentials the operator
  does not have in `.env`, and a new dependency); third-party mail libraries (no gain over
  `smtplib` for one plain-text message).

## R2 — Message format

- **Decision**: `email.message.EmailMessage` with `policy=email.policy.SMTP`, single `text/plain`
  UTF-8 part, quoted-printable transfer encoding, paragraphs as single lines, headers From
  (display name), To (bare address), Reply-To, Subject, Date, Message-ID only.
- **Rationale**: plain text with minimal headers looks like a personal message (docs/plan.md §2).
  Quoted-printable keeps accents safe through any relay. Hard-wrapped lines render badly on
  phones, where most replies come from.
- **Alternatives considered**: `format=flowed` (inconsistent client support); 8bit transfer
  (fine for SES but not every downstream hop); `List-Unsubscribe` header (helps bulk senders, but
  marks the email as bulk and is not needed at this volume — opt-out is by reply, handled in
  the manual inbox check).

## R3 — Connection strategy

- **Decision**: open, log in, send and quit for every email.
- **Rationale**: at 20 per hour the gap between emails (~3 minutes) exceeds typical idle
  timeouts; a fresh connection also scopes each failure to one attempt, which keeps the outcome
  classification exact.
- **Alternatives considered**: one long-lived connection with reconnect logic (more states to get
  wrong for no speed benefit at this pace).

## R4 — Classifying SMTP outcomes

- **Decision**: the table in plan D12 — accepted; 5xx recipient refusal = permanent rejection
  (bounced); SES 454 throttling, SES 554 "not verified", sender refusal, authentication and other
  data-stage 5xx stop the run without blaming the contact; a disconnect or timeout during the
  transaction is `unknown`.
- **Rationale**: SES normally accepts at SMTP time and bounces later (by email, reviewed in the manual inbox check), so rejections
  during sending are mostly account or configuration problems; marking those as contact bounces
  would wrongly suppress good addresses. A drop after DATA may still have delivered the email,
  so it must never be retried.
- **Alternatives considered**: retrying every failure (risks duplicates); treating all 5xx as
  bounces (sandbox or content rejections would suppress valid contacts).

## R5 — Never emailing a contact twice

- **Decision**: commit a `pending` attempt row before the SMTP call, `UNIQUE(contact_id, campaign,
  step)`, convert leftover `pending` rows to `unknown` at the next production start, and keep
  contacts with `pending`/`unknown` attempts out of every first-email campaign.
- **Rationale**: an at-most-once guarantee survives crashes, power loss and Ctrl+C; the database
  constraint backs the application check (SC-001).
- **Alternatives considered**: marking after sending (a crash between send and mark causes a
  duplicate); relying on the in-memory list (lost on crash).
- **Note**: FR-012 blocks a contact after any attempt in the campaign, including a temporary
  failure that was certainly not delivered. This plan follows the spec literally; a later
  campaign name picks such contacts up again because their `times_contacted` is still 0.

## R6 — Pacing

- **Decision**: rolling hourly cap computed from `send_attempts.created_at` (so restarts cannot
  exceed it), base interval `3600 / hourly_cap` with ±20% random jitter, send window checked in
  `zoneinfo.ZoneInfo("America/Caracas")`, weekdays 08:00–17:00 by default.
- **Rationale**: evenly spaced, slightly irregular sending looks human and stays far below SES
  rate limits; storing the cap in the database makes it hold across runs.
- **Alternatives considered**: token bucket in memory (reset by restarts); cron-driven one email
  per run (more moving parts for the operator).

## R7 — Campaign configuration format

- **Decision**: `config/campaign.toml` read with the standard-library `tomllib`.
- **Rationale**: typed values (dates, integers, lists) with comments for the operator; no
  dependency; read-only is all that is needed.
- **Alternatives considered**: more `.env` keys (untyped, and `.env` is for secrets); JSON (no
  comments); YAML (new dependency).

## R8 — Template format and link detection

- **Decision**: plain-text file with an `Asunto:` first line and named placeholders
  (`{saludo}`, `{apertura}`, `{empresa}`, `{remitente}`); fallback phrases and the opt-out sentence
  live in `campaign.toml`; a conservative URL/domain regex and an HTML regex applied to the
  template, the phrases, and each rendered email.
- **Rationale**: the operator edits wording without code (FR-001); the renderer appends the
  opt-out sentence so it cannot be forgotten (FR-004); checking rendered text catches data such as
  a company name containing a domain, which mail clients would turn into a link.
- **Alternatives considered**: Jinja2 or `string.Template` (conditionals invite complexity; a
  dependency for Jinja2); letting the template carry the opt-out sentence (easy to delete by
  mistake).

## R9 — DMARC and SPF preflight

- **Decision**: dnspython TXT lookups of `_dmarc.<sender domain>` and `<sender domain>`.
- **Rationale**: dnspython is already a dependency; the spec requires blocking on missing DMARC
  unless forced; SPF is informational (with SES's default MAIL FROM, SPF alignment comes from
  `amazonses.com`, and DMARC alignment relies on DKIM).
- **Alternatives considered**: `dig` subprocess (platform dependent); skipping SPF (the operator
  asked to fix it, so reporting it helps).
- **Operator note**: a starting DMARC record is `_dmarc.dvconsultores.com TXT "v=DMARC1; p=none"`
  (reporting address optional); the operator publishes it manually.

## R10 — Preventing two production runs at once

- **Decision**: `fcntl.flock(LOCK_EX | LOCK_NB)` on `<db path>.send.lock` held for the whole
  production run.
- **Rationale**: two concurrent runs would double the hourly rate and the recovery step of one
  could mark the other's live `pending` attempt as `unknown`. The lock is released automatically if
  the process dies.
- **Alternatives considered**: a lock row in the database (stale after crashes); PID files (need
  staleness checks).

## R11 — Test mode data

- **Decision**: test emails use only the synthetic `[test_sample]` values from `campaign.toml`
  (full, without name, without city); recipients come from `TEST_RECIPIENTS` in `.env`.
- **Rationale**: Constitution IV allows contact data to leave the machine only as an email to that
  contact; synthetic samples still exercise rendering, fallbacks and inbox placement (SC-005).
  Keeping the operator's own addresses in `.env` keeps them out of files shared with DeepSeek.
- **Alternatives considered**: rendering real prospects to test addresses (violates IV);
  test addresses in `campaign.toml` (personal data in a config file the executor may read).

## R12 — Schema evolution

- **Decision**: ordered migrations keyed by `PRAGMA user_version`; v1→v2 adds `runs` and
  `send_attempts`; a later migration adds v3 if inbox processing is automated.
- **Rationale**: keeps spec 001's contacts and tracking data intact; each migration runs once in a
  transaction.
- **Alternatives considered**: separate database file for sending (joins and atomic updates across
  files are awkward); migration framework (overkill).
