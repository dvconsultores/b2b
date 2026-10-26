# Tasks: Artemisa P2P Founders Campaign

Classification: DEEPSEEK for helpers pinned verbatim in plan.md; CLAUDE for credentials, the send
path, contact selection and the Telegram session.

**Deviation (2026-10-25):** the DeepSeek MCP server is not configured on this machine, so T003–T004
were implemented by Claude against the pinned decisions; the owner may re-delegate them for a rewrite.

- [x] T001 CLAUDE Constitution 1.4.0 → 1.5.0 (scope I/III/SES to the nómina campaigns; Artemisa
      HTML + inline images + Telegram handle from Gmail) — user request
- [x] T002 (dropped with the phone column: `b2b/phones.py` removed)
- [x] T003 [P] DEEPSEEK `b2b/artemisa_config.py` (D2, D3) + `tests/test_artemisa_config.py`.
      DoD: loader and template follow D2/D3 with the exact error messages; defaults applied;
      `render_artemisa` greets `Carlos` for first name `CARLOS` and without name when empty;
      body ends with the opt-out line; tests build TOML/template files in `tmp_path`.
      Pattern: `tests/test_campaign.py`, `tests/test_template.py`.
- [x] T004 [P] DEEPSEEK `b2b/artemisa_csv.py` (D5) + `tests/test_artemisa_csv.py`.
      DoD: reader follows D5; missing header → `InputError`; rejected counts always carry the
      five keys; synthetic rows only (`ana@example.com`, `+10000000000`); `pytest` passes.
- [x] T005 CLAUDE `b2b/artemisa_store.py` (D4) + `tests/test_artemisa_store.py`
- [x] T006 CLAUDE `b2b/mailer.py`: `load_gmail_settings`, `send_message` (D6) + `tests/test_mailer.py`
- [x] T007 CLAUDE `b2b/send_artemisa.py` (D7, D8) + conftest `artemisa_env` + `tests/test_send_artemisa.py`
- [x] T008 CLAUDE `config/artemisa.toml`, `config/templates/artemisa.txt` (D2, D10)
- [x] T009 (dropped at the user's request: Telegram check removed, `telethon` not a dependency)
- [x] T010 CLAUDE Docs: `.env.example`, `docs/deployment.md`, `docs/CHANGELOG.md`, `.claude/CLAUDE.md`
- [x] T011 CLAUDE Real import + preview on `contactos/artemisa.csv` (counts only); full suite
- [ ] T012 OPERATOR: fill `ARTEMISA_GMAIL_*` in `.env`, `--mode test`, then `--mode send`
