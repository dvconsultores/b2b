# Tasks: SES Bounce Guard

**Input**: `specs/003-ses-bounce-guard/plan.md` (D1–D5). All tasks are CLAUDE (credentials, send path,
suppression — `.claude/CLAUDE.md` exceptions). Tests use fakes only; no network.

## Phase 1: Setup

- [x] T001 Pin `boto3==1.43.93` in `requirements.txt`

## Phase 2: User Story 1 — Sync bounces and complaints (P1)

- [x] T002 [US1] Implement `b2b/ses_api.py` per D1
- [x] T003 [US1] Implement `b2b/bounces.py` per D2
- [x] T004 [US1] Implement `b2b/sync_bounces.py` per D3
- [x] T005 [US1] Tests in `tests/test_bounces.py` (apply, dry run, pagination, statistics, error codes, settings, command output and exit codes)

## Phase 3: User Story 2 — Live bounce guard (P1)

- [x] T006 [US2] Add `--ses-guard` to `b2b/send_first_email.py` per D4
- [x] T007 [US2] Tests in `tests/test_ses_guard.py` (missing keys, 24 h refusal, mid-batch stop, API failure, clean batch, send-only option)
- [x] T008 [US2] Entrypoint `send --ses-guard` and `sync-bounces` in `docker-entrypoint.sh` per D5

## Phase 4: Polish

- [x] T009 Full suite `.venv/bin/python -m pytest -q`
- [x] T010 Docs: `docs/deployment.md`, `.env.example`, spec 002 CLI contract, `.claude/CLAUDE.md`, `docs/CHANGELOG.md`
- [x] T011 Local image build check (boto3 present, no secrets or data inside)
- [x] T012 Real dry-run sync against SES and the local database (counts only; authorized by the user)
