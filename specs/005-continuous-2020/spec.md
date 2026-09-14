# Feature Specification: Continuous Sending to the 2020 List

**Feature Branch**: `005-continuous-2020`

**Created**: 2026-09-14

**Status**: Implemented (user request)

**Input**: After the first batch bounced at 18%, the user declined a paid verification service and
asked: "start the server, keep sending email; if the bounce is at an accepted level keep sending,
otherwise stop; use 2020 only, ignore 2009."

## User Scenarios & Testing

### US1 — One launch keeps sending while bounces stay acceptable (P1)

The operator launches the container once. It sends batch after batch (100 each, 20/hour, inside the
send window) until every eligible 2020 contact was emailed, or a guard stops it. The SES bounce
guard (spec 003) runs before every email; the bounce rate since launch above 2% (after 20 sends)
stops the run, and the campaign stays paused.

**Acceptance**: continuous campaign with batch limit 1 sends all eligible contacts in separate runs
and ends `all_sent`; a bounce over the threshold stops the run across batch boundaries; a
non-continuous campaign still sends one batch.

### US2 — 2020 contacts only, without verification (P1)

The campaign selects only contacts from the 2020 client file, including never-verified ones.
Contacts marked invalid by a verification import (spec 004) stay excluded.

### US3 — Launch waits for yesterday's bounces to age out (P2)

When the SES bounce rate of the last 24 hours is above the threshold at launch and the run waits
for the send window, it checks again every 30 minutes instead of refusing.

## Requirements

- **FR-001**: `config/campaign.toml` keys `source_years` (subset of 2020, 2009; default both) and
  `continuous` (bool, default false); `allowed_verification` may include `unverified`.
- **FR-002**: Real campaign `primer-contacto-2026-b`: `source_years = [2020]`,
  `allowed_verification = ["valid", "unverified"]`, `continuous = true`.
- **FR-003**: Each batch is its own `runs` row; the SES bounce rate is measured since the launch.
- **FR-004**: One counts-only summary email at the end of the launch.

## Success Criteria

- **SC-001**: The run never continues past the first check that shows the bounce rate above 2%
  (after 20 sends).

## Assumptions

- The 2020 list bounced at 18% in the first batch; the run is expected to stop after roughly 20–30
  emails unless the remaining addresses are much better. The user accepted this.
