# Implementation Plan: SES Bounce Guard

**Branch**: `003-ses-bounce-guard` | **Date**: 2026-09-14 | **Spec**: [spec.md](spec.md)

## Technical Context

Python 3.13; new dependency **boto3 1.43.93** (pinned in `requirements.txt`, shipped in the image);
read-only IAM user `b2b-ses-readonly` with `ses:GetAccount`, `ses:GetSendQuota`,
`ses:GetSendStatistics`, `ses:ListSuppressedDestinations`, `ses:GetSuppressedDestination`,
`cloudwatch:GetMetricData`. No schema change (uses `contacts.bounced` / `opted_out`).

## Constitution Check

| Principle | Status |
|-----------|--------|
| I. Sender Reputation First | Strengthened: pause on the provider's real bounce rate, not only SMTP-time rejections. |
| II. Never Contact Twice or Unwillingly | Complaints → opted out; bounces → bounced; both excluded from eligibility. |
| III. Plain, Human First Contact | N/A |
| IV. Contact Data Stays Local | Suppressed addresses come from the configured email provider and are only written to the local/server database; output is counts only. |
| V. Safe by Default | Guard failure stops sending; `sync_bounces --dry-run`. |
| VI. Simple, Reviewable Steps | One small wrapper module, one command, one guard class. |

## Pinned Decisions

- **D1 — `b2b/ses_api.py`**: `load_aws_settings(env_path)` (missing or `<placeholder>` key → `ConfigError`),
  `make_clients(settings)` (boto3 session with explicit keys; `sesv2` + `ses` clients),
  `list_suppressed(clients)` (all pages, emails stripped + lowercased, timestamps UTC),
  `send_statistics(clients, since)` (sum of data points with `Timestamp >= since`). Every API
  exception becomes `SesApiError(<AWS error code or exception type>)`.
- **D2 — `b2b/bounces.py`**: `apply_suppressions(conn, suppressed, dry_run=False) -> SyncResult`
  (suppressed, matched, newly_bounced, newly_opted_out, already_marked, not_in_database, ignored);
  BOUNCE → `bounced = 1, bounced_at`; COMPLAINT → `opted_out = 1, opted_out_at`; other reasons
  ignored; all writes in one transaction; `WHERE … = 0` so nothing is overwritten.
- **D3 — `b2b/sync_bounces.py`**: `python -m b2b.sync_bounces [--db] [--env] [--dry-run]`; exit 0,
  1 (config / SES API error), 2 (database missing or error); one counts-only output line.
- **D4 — Guard in `send_first_email`**: `--ses-guard` (send-only). After the batch-hold gate: load
  keys (`ConfigError` → exit 1), sync, and refuse (exit 3, `ses_bounce_rate`) when
  `bounce_exceeded(bounces, attempts, threshold, min_sends)` over the last 24 h; `SesApiError` →
  exit 1. Before each email (after the launch-price check): sync, then the same check since the
  run started → stop `ses_bounce_rate`; `SesApiError` → stop `ses_check_failed`. After the run:
  sync (errors ignored) before the summary bounce figures. `main(..., ses_clients=None)` for tests.
- **D5 — Container**: entrypoint `send` adds `--ses-guard`; new `sync-bounces [--dry-run]` command;
  server `.env` needs the three `AWS_*` keys.

## Project Structure

```text
b2b/ses_api.py  b2b/bounces.py  b2b/sync_bounces.py  b2b/send_first_email.py (guard)
docker-entrypoint.sh  requirements.txt
tests/test_bounces.py  tests/test_ses_guard.py
```

## Complexity Tracking

None.
