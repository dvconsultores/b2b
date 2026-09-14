# Feature Specification: SES Bounce Guard

**Feature Branch**: `003-ses-bounce-guard`

**Created**: 2026-09-14

**Status**: Implemented (authorized by the user after the first batch was stopped)

**Input**: First production batch (campaign `primer-contacto-2026`) was stopped by the operator
after the SES API showed 65 delivery attempts and 10 bounces (15.4%) on 2026-09-14. SES accepts
every email at SMTP time and reports bounces later, so spec 002's pause rule never saw them.
The user asked for a bounce sync from SES and a live bounce check before each email.

Replaces the dropped automatic inbox reading (former spec 003) for bounces and complaints only;
replies are still checked by hand.

## User Scenarios & Testing

### US1 — Sync bounces and complaints from SES (P1)

The operator runs one command; every address on the SES account suppression list that matches a
contact is marked bounced (reason BOUNCE) or opted out (reason COMPLAINT), so it is never emailed
again. A dry run shows the counts without writing.

**Acceptance**: matching is case-insensitive; already-marked contacts are counted, not changed;
addresses not in the database are counted; output shows counts only.

### US2 — Live bounce guard while sending (P1)

A production run with the guard refuses to start when SES reports a bounce rate above the
campaign threshold over the last 24 hours, and stops before the next email when the SES bounce
rate since the run started exceeds it. Before each email the database is synced from the
suppression list, so the campaign bounce rule sees real bounces too. If the SES API cannot be
reached the run stops instead of sending blind.

**Acceptance**: missing AWS keys → exit 1 before any SMTP connection; high 24 h rate → exit 3,
nothing sent; bounce during the run → stop reason `ses_bounce_rate`, exit 4, bounced contact
marked; API failure mid-run → stop reason `ses_check_failed`; clean batch completes.

## Requirements

- **FR-001**: Read-only SES access with a separate IAM key from `.env` (`AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, default `us-east-2`); credentials never printed.
- **FR-002**: `sync_bounces` applies the whole suppression list; tracking fields only go 0 → 1;
  `bounced_at` / `opted_out_at` = the suppression entry's last update time.
- **FR-003**: `send_first_email --ses-guard` (send mode only) syncs before starting and before
  every email, and after the run before the summary.
- **FR-004**: Guard thresholds reuse the campaign's `bounce_pause_threshold` and
  `bounce_min_sends`; the SES rate is bounces ÷ delivery attempts from `GetSendStatistics`.
- **FR-005**: The Docker `send` command always uses `--ses-guard`; `sync-bounces` is available as an
  entrypoint command.
- **FR-006**: No email is sent by any of this; output is counts only.

## Success Criteria

- **SC-001**: A batch whose recipients bounce stops within one email after the SES bounce rate
  crosses the threshold (after `bounce_min_sends` attempts).
- **SC-002**: After a sync, every suppressed address present in the database is excluded from
  eligibility.

## Assumptions

- SES statistics are account-wide: other applications sending from the same SES account count
  toward the rate (conservative).
- `GetSendStatistics` has 15-minute granularity and a short delay; the suppression list catches
  hard bounces as SES records them.
- Complaints are treated as opt-outs (Constitution II).
