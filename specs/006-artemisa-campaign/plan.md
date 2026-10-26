# Implementation Plan: Artemisa P2P Founders Campaign

**Branch**: `006-artemisa-campaign` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

## Constitution Check (v1.5.0)

| Principle | Status |
|-----------|--------|
| I. Sender Reputation First | Pass as amended: Artemisa sends from the platform's Gmail account under `hourly_cap` and `daily_cap`; a permanent-rejection rate guard pauses the run. The list is the platform's own verified users (every email syntactically valid, 95% gmail.com). |
| II. Never Contact Twice or Unwillingly | Pass: spec 002 `send_attempts` tracking reused (`UNIQUE (contact_id, campaign, step)`), pending recovery, `bounced` / `opted_out` exclusion, opt-out line in every email. |
| III. Plain, Human First Contact | Amended 1.5.0: applies to the B2B nómina first email. The Artemisa announcement is HTML + plain text with two inline images and the Telegram handle, because the platform's own users expect its branding. No tracking pixels, no external resources. |
| IV. Contact Data Stays Local | Pass: `contactos/artemisa.csv`, `data/artemisa.sqlite3` and previews stay local; only `user_id, email, first_name, nickname, types` are stored (no phone, no KYC name). |
| V. Safe by Default | Pass: default mode `preview`; `send` needs the campaign name; counts-only summaries. |
| VI. Simple, Reviewable Steps | Pass: no new dependency; CSV in, SQLite + preview file out. |

## Pinned Decisions

- **D2 — Campaign config** (`b2b/artemisa_config.py`, DeepSeek): `load_artemisa_campaign(path)
  -> ArtemisaCampaign`, same validation style and `ConfigError` messages as `b2b/campaign.py`
  (`{path}: unknown key 'x'`, `missing key 'x'`, `'x' has the wrong type`, `'x' is invalid`).
  Keys (top level): `name` (required, `^[a-z0-9][a-z0-9-]{2,49}$`), `template` (required,
  non-empty str → `Path`), `images` (list of 1–3 non-empty str → `tuple[Path, ...]`, default
  `[]` is invalid: at least one), `timezone` (default `America/Caracas`, must load with
  `ZoneInfo`), `hourly_cap` (int 1–100, default 40), `daily_cap` (int 1–500, default 400),
  `send_days` (non-empty unique subset of mon…sun, default all seven), `send_start` / `send_end`
  (`HH:MM`, defaults `09:00` / `21:00`, end > start), `bounce_pause_threshold` (number in
  (0, 0.2), default 0.05), `bounce_min_sends` (int 1–500, default 20),
  `temporary_failure_limit` (int 1–10, default 3); tables `[phrases]` with exactly
  `greeting_with_name` (placeholders exactly `{nombre}`), `greeting_without_name` (no
  placeholders), `opt_out` (no placeholders) and `[test_sample]` with exactly `nombre`.
  Phrase strings must not contain HTML (`campaign.HTML_PATTERN`); links are allowed.
  `ArtemisaCampaign` is a frozen dataclass with those fields (`send_start`/`send_end` as
  `datetime.time`, `send_days` tuple, `images` tuple of `Path`) **plus `step: int = 1`** so
  `b2b.pacing` and `b2b.preview.write_preview` accept it unchanged (they read `timezone`,
  `send_days`, `send_start`, `send_end`, `hourly_cap`, `name`, `step`).

- **D3 — Template and rendering** (`b2b/artemisa_config.py`, DeepSeek):
  `load_artemisa_template(path, opt_out) -> template.Template` with the spec 002 file format
  (line 1 `Asunto: <subject>`, line 2 empty, body from line 3, trailing blank lines dropped):
  subject placeholders: none allowed; body placeholders: subset of `{saludo}`, `{remitente}`;
  `ConfigError` messages as `b2b/template.py` (`line 1 must be 'Asunto: <subject>'`, `line 2 must
  be empty`, `body is empty`, `unknown placeholder 'x'`, `invalid braces`, `HTML not allowed in
  template`, `remove the opt-out sentence; it is added automatically`). Links/domains ARE allowed
  (the template names `t.me/artemisa_p2p_bot`), so `LINK_PATTERN` is not applied.
  `render_artemisa(tmpl, phrases, *, to, contact_id, first_name, sender_name) ->
  template.RenderedEmail`: `nombre = template.first_name(first_name)` (reuse; it title-cases
  `CARLOS` → `Carlos`); greeting with or without name; body =
  `tmpl.body.format(saludo=..., remitente=sender_name) + "\n\n" + phrases.opt_out + "\n"`.

- **D4 — Tracker** (`b2b/artemisa_store.py`, Claude): database `data/artemisa.sqlite3`,
  `PRAGMA user_version = 1`. Tables: `contacts` (`id`, `user_id INTEGER NOT NULL UNIQUE`,
  `email TEXT NOT NULL UNIQUE`, `first_name`, `nickname`, `types`,
  and the spec 002 tracking columns `times_contacted`, `last_contacted_at`,
  `bounced`, `bounced_at`, `responded`, `responded_at`, `opted_out`, `opted_out_at` with the same
  CHECKs, `created_at`, `updated_at`); `runs` and `send_attempts` exactly as `b2b/store.py`
  (same DDL constants reused) so `b2b.tracking` works unchanged. `ensure_schema` refuses a
  database whose `contacts` table lacks `user_id` ("not an Artemisa database"). Upsert refreshes
  only `email`-independent descriptive columns (`first_name`, `nickname`, `phone`, `types`) keyed
  by `user_id`; an email that now belongs to a different `user_id` is reported `conflict` and
  skipped. Selection: `bounced = 0 AND opted_out = 0 AND id NOT IN (SELECT contact_id FROM
  send_attempts WHERE campaign = ? AND step = 1) ORDER BY id`.

- **D5 — CSV reader** (`b2b/artemisa_csv.py`, DeepSeek): `read_artemisa_csv(path) -> CsvResult`
  with `rows: list[ArtemisaRow]` (`user_id: int, email: str, first_name: str, nickname: str,
  types: str`) and `rejected: dict[str, int]` with the keys `invalid_user_id`,
  `invalid_email`, `duplicate_user_id`, `duplicate_email` (always present, 0 when none). Encoding `utf-8-sig`, `csv.DictReader`.
  Required headers (`InputError` naming the file and the missing header otherwise): `user_id`,
  `email`, `first_name`, `nickname`, `types`; other columns (including `phone`) ignored. Rules per row:
  `user_id` → `int(strip)` must be > 0; email → `emails.normalize_token` then `emails.validate`
  is `None`; first duplicate wins; `first_name`, `nickname`, `types` stripped.

- **D6 — Gmail settings** (`b2b/mailer.py`, Claude): `load_gmail_settings(env_path, *,
  require_test_recipients) -> SenderSettings(host="smtp.gmail.com", port=465,
  user=ARTEMISA_GMAIL_USER, password=ARTEMISA_GMAIL_PASS, sender=ARTEMISA_GMAIL_USER,
  from_name=ARTEMISA_GMAIL_FROM_NAME, test_recipients=TEST_RECIPIENTS)`; `ARTEMISA_GMAIL_USER`
  must be a valid address; errors as `load_sender_settings`. `send_email` is split so that
  `send_message(settings, message: EmailMessage, to: str, smtp_factory=None) -> SendOutcome`
  carries the SMTP call and outcome classification for any prebuilt message; `send_email`
  builds the plain message and delegates. Gmail's `421 4.7.0` / `454` map to
  `provider_throttled`; `550 5.4.5 Daily user sending limit exceeded` arrives as
  `SMTPDataError` 550 → `message_rejected` (a stop kind), which ends the run. `--sender ses` (added at the user's request for
  testing) uses `load_sender_settings` (SES keys) with `ARTEMISA_GMAIL_FROM_NAME` as display name
  when set (`load_artemisa_ses_settings`).

- **D7 — Message** (`b2b/send_artemisa.py`, Claude): `build_artemisa_message(settings, email,
  images: Sequence[tuple[str, bytes]], now) -> EmailMessage`: headers as spec 002
  (`From`, `To`, `Reply-To`, `Subject`, `Date`, `Message-ID`); `set_content(plain)`;
  `add_alternative(html, subtype="html")`; each image `add_related(data, maintype="image",
  subtype="png", cid=<make_msgid>, filename=<name>)` on the HTML part. HTML: escaped body
  paragraphs (`<p>` per blank-line block, `<br>` per line), then one `<img src="cid:…"
  width="540" alt="Artemisa P2P">` per image, max-width 100%, no CSS from outside, no scripts.

- **D8 — Send command** (`b2b/send_artemisa.py`, Claude): `python -m b2b.send_artemisa
  [--mode import|preview|test|send] [--csv contactos/artemisa.csv] [--config config/artemisa.toml]
  [--db data/artemisa.sqlite3] [--env .env] [--sender gmail|ses] [--previews-dir data/previews]
  [--confirm NAME]
  [--wait-for-window] [--notify]`; exit codes as spec 002 (0 ok, 1 config, 2 database,
  3 refused, 4 stopped, 130 interrupted). `send`: `tracking.send_lock`, `recover_pending`,
  `check_login`, window check, print campaign / recipients / caps / window, confirmation,
  one `runs` row, loop: before each email `launch` guards in this order — bounce rate
  (`tracking.campaign_bounce` + `bounce_exceeded`), daily cap (`attempts in the last 24 h >=
  daily_cap` → stop `daily_cap`, or with `--wait-for-window` sleep until the oldest of them is
  24 h old), hourly cap (`pacing.cap_wait_seconds`), window (`pacing.window_contains`); jittered
  interval `pacing.next_interval` between emails; `temporary_failure_limit`; stop kinds from
  `SendOutcome.stop`. Summary lines (counts only): mode/result, campaign, eligible, selected,
  previewed, test emails sent, accepted, permanent rejections, temporary failures, unknown,
  rejection rate, stop reason, next window, preview path. No DMARC/SPF preflight (gmail.com).
  Optional `--notify` emails the summary to `TEST_RECIPIENTS` from the same account.

- **D10 — Files**: `config/artemisa.toml`, `config/templates/artemisa.txt` (subject and body
  below), `.env.example` keys, `docs/deployment.md` section
  "Artemisa campaign (local)", `docs/CHANGELOG.md`, `.claude/CLAUDE.md` stack note and egress
  rule (`ARTEMISA_GMAIL_*`).

  Template body (user's text, typos corrected; `{saludo}` and `{remitente}` rendered):

  ```
  Asunto: Sé fundador en Artemisa P2P: monta tu oferta y opera sin custodia

  {saludo}

  Sé fundador: monta tu oferta. Artemisa P2P es descentralizada y con reglas claras: conectas tu wallet de Telegram y operas, sin custodia y sin letras pequeñas.

  Ingresa en @artemisa_p2p_bot (t.me/artemisa_p2p_bot) y publica tu primera oferta hoy.

  Saludos,
  {remitente}
  ```

- **D11 — Tests**: synthetic fixtures only; `tests/test_artemisa_config.py`,
  `tests/test_artemisa_csv.py` (DeepSeek); `tests/test_artemisa_store.py`,
  `tests/test_send_artemisa.py` (fake SMTP/clock from `tests/conftest.py`, Gmail `.env` fixture
  `artemisa_env` added to conftest) (Claude).

## Complexity Tracking

| Item | Why | Alternative rejected |
|------|-----|----------------------|
| Separate database `data/artemisa.sqlite3` | The spec 001 `contacts` schema (company key, source year CHECK 2009/2020, company exclusion) does not fit platform users; mixing lists would let the nómina eligibility rules act on Artemisa contacts. | Extending `store.py` with nullable columns and a `list` discriminator: wider change to the send path of specs 002–005. |
