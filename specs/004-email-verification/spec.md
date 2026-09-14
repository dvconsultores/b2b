# Feature Specification: Email Verification Before Sending

**Feature Branch**: `004-email-verification`

**Created**: 2026-09-14

**Status**: Implemented (user chose "Verification service" after the first batch)

**Input**: The first batch of campaign `primer-contacto-2026` reached 61 accepted emails and 11
bounces (18%) before the operator stopped it. The domain (MX) check of spec 001 does not show
whether a mailbox still exists; the 2020 and 2009 lists are 6 and 17 years old. The user chose to
verify the remaining addresses with a paid verification service before any further sending.

## User Scenarios & Testing

### US1 — Export addresses to verify (P1)

The operator runs one command on the server and gets a CSV with a single `email` column: every
personal contact that could still receive a first email and was never verified. Contacts already
emailed, bounced, replied, opted out, generic, or at a company that already received the first
email are left out (no credits spent on addresses that will never be used).

**Acceptance**: file has only the `email` header and addresses; owner-only permissions; the command
refuses to overwrite; output shows the count and path only.

### US2 — Import the service's results (P1)

The operator downloads the results CSV from NeverBounce or ZeroBounce and imports it. Each matching
contact is marked `valid`, `catch_all`, `unknown` or `invalid`. A dry run shows the counts.

**Acceptance**: NeverBounce (`result`) and ZeroBounce (`ZB Status`) layouts are recognized; other
layouts work with `--email-column` / `--status-column`; if any row has an unrecognized status
nothing is imported and no cell value is printed.

### US3 — Send only to verified addresses (P1)

A campaign sends only to contacts whose verification is in `allowed_verification` (default
`["valid"]`). When the best contact of a company is not verified, a verified colleague is chosen.
The summary shows how many candidates were skipped as not verified. A company that already received
the first email in any campaign is not emailed again.

**Acceptance**: unverified and invalid contacts are never selected; `catch_all` only when allowed;
the next campaign `primer-contacto-2026-b` skips the companies emailed by `primer-contacto-2026`.

## Requirements

- **FR-001**: Schema v3 adds `contacts.verification` (`unverified` default, `valid`, `catch_all`,
  `unknown`, `invalid`) and `contacts.verified_at`; existing databases migrate automatically.
- **FR-002**: The export contains email addresses only (Constitution IV, v1.3.0).
- **FR-003**: Import is the only writer of verification fields; the contact import (spec 001) never
  changes them.
- **FR-004**: `allowed_verification` in `config/campaign.toml` may contain `valid`, `catch_all`,
  `unknown`; never `invalid` or `unverified`.
- **FR-005**: Company exclusion covers step-1 attempts (`accepted`, `pending`, `unknown`) in every
  campaign.
- **FR-006**: Docker commands `export-verification` and `import-verification <file>`.

## Success Criteria

- **SC-001**: The next campaign's bounce rate stays under the 2% pause threshold.
- **SC-002**: No address outside the export file is ever sent to the verification service.

## Assumptions

- The operator uploads and downloads files in the service's web interface; no API key is stored.
- Cost is about USD 0.008 per address (roughly 2,000 addresses).
- `catch_all` domains accept every address and can still bounce later; they stay excluded unless
  the operator adds them to `allowed_verification`.
