# Implementation Plan: Continuous Sending to the 2020 List

**Branch**: `005-continuous-2020` | **Date**: 2026-09-14 | **Spec**: [spec.md](spec.md)

## Constitution Check (v1.4.0)

| Principle | Status |
|-----------|--------|
| I. Sender Reputation First | Pass with amendment 1.4.0: consecutive batches only while the bounce rate checked before every email stays under 2%; 20/hour cap unchanged. 2020 addresses passed the spec 001 format and domain checks. |
| II. Never Contact Twice or Unwillingly | Unchanged (attempt tracking, bounced/opted-out exclusion, company exclusion across campaigns). |
| III–VI | Unchanged; no new dependency. |

## Pinned Decisions

- **D1 — Campaign** (`b2b/campaign.py`): `source_years` list of ints, non-empty, unique, subset of
  2020/2009, default `[2020, 2009]`; `continuous` bool, default false; `unverified` added to the
  allowed values of `allowed_verification`.
- **D2 — Eligibility**: `select_recipients(..., allowed_verification, source_years)` drops other
  years before counting.
- **D3 — Continuous loop** (`send_first_email._production_locked`): after `batch_complete`, when
  `campaign.continuous`, render the next batch; empty → stop reason `all_sent` (exit 0); else log,
  sleep one jittered interval and start a new `runs` row. Bounce rate since launch (`run_started`
  of the first batch). Confirmation block and summary email once per launch; `selected` adds up.
- **D4 — Launch wait**: with `--wait-for-window`, the SES 24-hour check sleeps
  `SES_RECHECK_SECONDS = 1800` and re-syncs until the rate is acceptable; without it, refuse (exit 3).
- **D5 — Tests**: `campaign_files` fixture sets neutral `allowed_verification = ["valid"]`,
  `source_years = [2020, 2009]`, `continuous = false` unless overridden; `tests/test_continuous.py`.

## Complexity Tracking

None.
