# Tasks: Email Verification Before Sending

**Input**: `specs/004-email-verification/plan.md` (D1–D8). All tasks CLAUDE (contact selection,
contact-data export, schema). Tests use synthetic data only.

- [x] T001 Constitution 1.3.0 (IV: email-only export to the named verification services) — user request
- [x] T002 Schema v3 migration in `b2b/store.py` (D1) + `tests/test_store.py`
- [x] T003 `b2b/verification.py` status mapping, CSV reading, apply (D2)
- [x] T004 Eligibility changes and `verification_candidates` (D3) + `tests/test_eligibility.py`
- [x] T005 `allowed_verification` config and campaign rename (D4) + `tests/test_campaign.py`
- [x] T006 `b2b/export_verification.py` (D5)
- [x] T007 `b2b/import_verification.py` (D6)
- [x] T008 Summary line (D7) + `tests/test_send_report.py`; send/preview tests use the new campaign name
- [x] T009 Tests `tests/test_verification.py`; fixture default verified contacts
- [x] T010 Entrypoint commands (D8)
- [x] T011 Docs: CLI contract, `docs/deployment.md`, `b2b.yml` comment, CHANGELOG, `.claude/CLAUDE.md`
- [x] T012 Migration and counts on a copy of the local database (counts only; copy deleted)
- [ ] T013 OPERATOR: deploy, export on the server, verify with the service, import results
- [ ] T014 OPERATOR: preview `primer-contacto-2026-b`, then launch
