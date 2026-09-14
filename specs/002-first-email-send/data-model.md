# Data Model: First Outreach Email and Sending

**Feature**: 002-first-email-send | **Date**: 2026-09-13

Schema version 2 = spec 001's `contacts` (unchanged) + `runs` + `send_attempts`.

## `runs`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PRIMARY KEY | |
| `kind` | TEXT | NOT NULL CHECK IN ('send_production', 'inbox') | `inbox` rows are written by `mark_inbox_checked` |
| `campaign` | TEXT | NULL | campaign name for `send_production` |
| `step` | INTEGER | NULL | 1 for the first email |
| `started_at` | TEXT | NOT NULL | UTC `YYYY-MM-DDTHH:MM:SSZ` |
| `finished_at` | TEXT | NULL | set when the run ends normally or by a guard |
| `stop_reason` | TEXT | NULL | see Stop reasons |
| `forced_no_dmarc` | INTEGER | NOT NULL DEFAULT 0 CHECK IN (0, 1) | override recorded (FR-015) |

Index: `idx_runs_kind_started` on `(kind, started_at)`.

A crashed run keeps `finished_at` NULL; the batch hold uses `COALESCE(finished_at, started_at)`.

## `send_attempts`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | INTEGER | PRIMARY KEY | |
| `run_id` | INTEGER | NOT NULL REFERENCES runs(id) | |
| `contact_id` | INTEGER | NOT NULL REFERENCES contacts(id) | |
| `campaign` | TEXT | NOT NULL | |
| `step` | INTEGER | NOT NULL CHECK (step = 1) | later specs widen this |
| `status` | TEXT | NOT NULL CHECK IN ('pending', 'accepted', 'permanent_rejection', 'temporary_failure', 'unknown') | |
| `error_kind` | TEXT | NULL | see Error kinds |
| `smtp_code` | INTEGER | NULL | numeric reply code only |
| `message_id` | TEXT | NULL | set for `accepted` |
| `created_at` | TEXT | NOT NULL | written in the `pending` commit; drives the rolling cap |
| `finished_at` | TEXT | NULL | written with the outcome |

Constraints: `UNIQUE(contact_id, campaign, step)`; `CHECK ((status = 'pending') = (finished_at IS NULL))`;
`CHECK ((status = 'accepted') = (message_id IS NOT NULL))`.
Indexes: `idx_attempts_created` on `created_at`; `idx_attempts_campaign` on `(campaign, step, status)`.

### Attempt state transitions

```text
pending ──► accepted              (contact: times_contacted + 1, last_contacted_at = now)
pending ──► permanent_rejection   (contact: bounced = 1, bounced_at = now if not already bounced)
pending ──► temporary_failure     (no contact change)
pending ──► unknown               (no contact change; during the run, or at next production start with error_kind 'interrupted')
```

No other transition exists; finished attempts are never modified or deleted.

### Error kinds

`recipient_refused` (permanent), `recipient_deferred`, `data_deferred`, `connection_failed`,
`authentication_failed`, `sender_refused`, `provider_throttled`, `identity_not_verified`,
`message_rejected` (temporary), `connection_lost`, `interrupted` (unknown).
Stop-class kinds (end the run immediately): `connection_failed`, `authentication_failed`,
`sender_refused`, `provider_throttled`, `identity_not_verified`, `message_rejected`,
`connection_lost`, `interrupted`.

### Stop reasons

`batch_complete`, `launch_price_ended`, `bounce_threshold`, `window_closed`,
`temporary_failures`, `connection_lost`, or a stop-class error kind.

## `contacts` writes by this feature

Only inside the outcome commit of an attempt:

- `times_contacted = times_contacted + 1`, `last_contacted_at = now` — on `accepted`.
- `bounced = 1`, `bounced_at = now` — on `permanent_rejection`, only when `bounced = 0`.

`created_at`, `updated_at` and descriptive columns are never written by this feature.

## Derived values

- **Eligible contact**: plan D8.
- **Rolling hour count**: `SELECT COUNT(*) FROM send_attempts WHERE created_at > <now − 3600 s>`.
- **Campaign bounce rate**: `SUM(c.bounced) / COUNT(*)` over `send_attempts a JOIN contacts c`
  where `a.campaign = ? AND a.step = ? AND a.status IN ('accepted', 'permanent_rejection')`;
  evaluated only when `COUNT(*) >= bounce_min_sends`.
- **Batch hold satisfied**: no `send_production` run exists, or
  `EXISTS (SELECT 1 FROM runs WHERE kind = 'inbox' AND finished_at > <latest send_production COALESCE(finished_at, started_at)>)`.

## In memory (not stored)

- **Campaign** (from `campaign.toml`): see contracts/files.md.
- **Template**: subject text, body text.
- **SenderSettings** (from `.env`): host, port, user, password, sender, from name, test recipients.
- **RenderedEmail**: contact id (none in test mode), recipient, subject, body.
- **SendOutcome**: status, error_kind, smtp_code, message_id, stop (bool).
- **PreflightResult**: dmarc (`present` | `missing` | `unverified`), dmarc_policy, spf
  (`includes_ses` | `present_without_ses` | `missing` | `unverified`).
- **SendSummary**: mode, result, campaign, step, eligible, skipped_same_company,
  skipped_rendered_link, selected, previewed, test_sent, accepted, permanent_rejections,
  temporary_failures, unknown, bounce numerator/denominator, stop_reason, preview path, next window
  opening, DMARC/SPF status, forced flag.
