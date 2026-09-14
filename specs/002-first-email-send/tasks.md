---

description: "Task list for 002-first-email-send"
---

# Tasks: First Outreach Email and Sending

**Input**: Design documents from `specs/002-first-email-send/`

**Prerequisites**: plan.md (D1–D17), spec.md (US1–US4), research.md, data-model.md,
contracts/cli.md, contracts/files.md, quickstart.md; spec 001 implemented (`b2b/` package,
`data/b2b.sqlite3`)

**Tests**: Required (constitution Development Workflow, `.claude/CLAUDE.md` TEST step). Synthetic
data only (`example.com`, `example.org`, `example.net`); a fake SMTP class, fake clock and fake
resolver; the conftest network guard stays on. No test reads `contactos/`, `.env` or `data/`.

**Organization**: Setup → Foundational → US1 preview → US2 test send → US3 production send →
US4 DMARC preflight → Polish. Module tasks create the module and its test file together (≤ 2
files).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 from spec.md
- Indented lines are part of the task (pinned details and **DoD**).

## Shared interface (pinned — all tasks)

Spec 001 names (`b2b.ConfigError`, `b2b.emails.validate`, `b2b.store.*`, `b2b.domains.*`) keep their
existing signatures. New public names:

```python
# b2b/store.py (changed)
SCHEMA_VERSION = 2
def ensure_schema(conn: sqlite3.Connection) -> None      # creates v1, then migrates 1→2; > 2 → SchemaError

# b2b/campaign.py
LINK_PATTERN: re.Pattern[str]   # re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|ve|co|io|info|biz|app|dev|me)\b)", re.IGNORECASE)
HTML_PATTERN: re.Pattern[str]   # re.compile(r"(</?[a-z][^>]*>|&[a-z]+;)", re.IGNORECASE)
def contains_link_or_html(text: str) -> bool
@dataclass(frozen=True)
class Phrases:
    greeting_with_name: str; greeting_without_name: str; opening_with_city: str
    opening_without_city: str; company_fallback: str; opt_out: str
@dataclass(frozen=True)
class TestSample:
    nombre: str; empresa: str; ciudad: str
@dataclass(frozen=True)
class Campaign:
    name: str; step: int; template: Path; launch_price_end: date; timezone: str
    hourly_cap: int; batch_limit: int; send_days: tuple[str, ...]; send_start: time; send_end: time
    bounce_pause_threshold: float; bounce_min_sends: int; temporary_failure_limit: int
    test_sample_count: int; phrases: Phrases; test_sample: TestSample
def load_campaign(path: Path) -> Campaign

# b2b/template.py
@dataclass(frozen=True)
class Template:
    subject: str; body: str
@dataclass(frozen=True)
class RenderedEmail:
    contact_id: int | None; to: str; subject: str; body: str
SUBJECT_PLACEHOLDERS = frozenset({"empresa"})
BODY_PLACEHOLDERS = frozenset({"saludo", "apertura", "remitente"})
HONORIFICS = frozenset({"ing", "lic", "licda", "dr", "dra", "sr", "sra", "srta", "abg", "arq", "econ", "prof", "msc", "mba", "tsu"})
def load_template(path: Path, opt_out: str) -> Template
def display_company(company: str, fallback: str) -> str
def first_name(contact_name: str) -> str
def render(template: Template, phrases: Phrases, *, to: str, contact_id: int | None,
           company: str, contact_name: str, city: str, sender_name: str) -> RenderedEmail
def rendered_has_link(email: RenderedEmail) -> bool

# b2b/preflight.py
@dataclass(frozen=True)
class PreflightResult:
    dmarc: str                 # "present" | "missing" | "unverified"
    dmarc_policy: str | None
    spf: str                   # "includes_ses" | "present_without_ses" | "missing" | "unverified"
def make_resolver(timeout: float = 5.0) -> dns.resolver.Resolver
def check_sender_domain(domain: str, resolver: object) -> PreflightResult

# b2b/preview.py
def write_preview(previews_dir: Path, campaign: Campaign, emails: Sequence[RenderedEmail],
                  generated_at: datetime) -> Path

# b2b/send_report.py
@dataclass            # mutable
class SendSummary:
    mode: str; result: str; campaign: str; step: int
    eligible: int = 0; skipped_same_company: int = 0; skipped_rendered_link: int = 0
    selected: int = 0; previewed: int = 0; test_sent: int = 0; accepted: int = 0
    permanent_rejections: int = 0; temporary_failures: int = 0; unknown: int = 0
    bounced: int = 0; bounce_base: int = 0; dmarc: str = "-"; spf: str = "-"
    forced_no_dmarc: bool = False; stop_reason: str = "-"; next_window: str = "-"
    preview_path: str = "-"
def format_send_summary(summary: SendSummary) -> str

# b2b/mailer.py
@dataclass(frozen=True)
class SenderSettings:
    host: str; port: int; user: str; password: str = field(repr=False); sender: str = ""
    from_name: str = ""; test_recipients: tuple[str, ...] = ()
@dataclass(frozen=True)
class SendOutcome:
    status: str                # "accepted" | "permanent_rejection" | "temporary_failure" | "unknown"
    error_kind: str | None; smtp_code: int | None; message_id: str | None; stop: bool
STOP_KINDS = frozenset({"connection_failed", "authentication_failed", "sender_refused", "provider_throttled",
                        "identity_not_verified", "message_rejected", "connection_lost", "interrupted"})
def load_sender_settings(env_path: Path, *, require_test_recipients: bool) -> SenderSettings
def default_smtp_factory(settings: SenderSettings) -> smtplib.SMTP
def build_message(settings: SenderSettings, email: RenderedEmail, now: datetime) -> EmailMessage
def check_login(settings: SenderSettings, smtp_factory: Callable | None = None) -> str | None
def send_email(settings: SenderSettings, email: RenderedEmail, now: datetime,
               smtp_factory: Callable | None = None) -> SendOutcome

# b2b/eligibility.py
@dataclass(frozen=True)
class Recipient:
    contact_id: int; email: str; company: str; company_key: str; contact_name: str
    city: str; source_year: int
@dataclass(frozen=True)
class Selection:
    recipients: list[Recipient]; eligible: int; skipped_same_company: int
def select_recipients(conn: sqlite3.Connection, campaign: str, step: int) -> Selection

# b2b/tracking.py
class SendLockBusy(Exception): ...
@contextmanager
def send_lock(db_path: Path) -> Iterator[None]
def recover_pending(conn: sqlite3.Connection, now: str) -> int
def batch_hold_satisfied(conn: sqlite3.Connection) -> bool
def start_run(conn, campaign: str, step: int, forced_no_dmarc: bool, now: str) -> int
def finish_run(conn, run_id: int, stop_reason: str, now: str) -> None
def record_pending(conn, run_id: int, contact_id: int, campaign: str, step: int, now: str) -> int
def record_outcome(conn, attempt_id: int, contact_id: int, outcome: SendOutcome, now: str) -> None
def attempts_in_last_hour(conn, now: datetime) -> tuple[int, str | None]     # (count, oldest created_at)
def campaign_bounce(conn, campaign: str, step: int) -> tuple[int, int]      # (bounced, base)
def bounce_exceeded(bounced: int, base: int, threshold: float, min_sends: int) -> bool

# b2b/pacing.py
def local_now(campaign: Campaign, moment: datetime) -> datetime
def window_contains(campaign: Campaign, moment: datetime) -> bool
def next_window_start(campaign: Campaign, moment: datetime) -> datetime
def next_interval(campaign: Campaign, rng: random.Random) -> float
def cap_wait_seconds(count: int, oldest_created_at: str | None, hourly_cap: int, now: datetime) -> float
def launch_price_passed(campaign: Campaign, moment: datetime) -> bool

# b2b/send_first_email.py
def main(argv: list[str] | None = None, *, smtp_factory=None, resolver=None, now=None,
         sleep=None, ask=None, rng=None) -> int
```

---

## Phase 1: Setup

- [x] T001 [P] Create `config/campaign.toml` with the initial content in contracts/files.md
  - **DoD**: file byte-matches the contract's initial content block; `tomllib.load` parses it.
- [x] T002 [P] Create `config/templates/primer_contacto.txt` with the initial content in contracts/files.md
  - UTF-8, `\n` endings, trailing newline after `{remitente}`.
  - **DoD**: file matches the contract block exactly; line 1 starts `Asunto: `; line 2 empty.
- [x] T003 [P] Operator adds `TEST_RECIPIENTS=<own addresses, comma-separated>` to `.env` (1–5 addresses on at least two providers)
  - **DoD**: operator confirms; Claude verifies only that the key exists and parses to 1–5 valid addresses, printing the count.

---

## Phase 2: Foundational

**⚠️ CRITICAL**: no user story work can begin until this phase is complete

- [x] T004 [P] Add the schema v2 migration to `b2b/store.py` with tests in `tests/test_store.py` per plan D3 and data-model.md
  - `SCHEMA_VERSION = 2`; `ensure_schema`: version 2 → no-op; > 2 → `SchemaError`; 0 without `contacts` → create v1 in one transaction, then migrate; 0 with `contacts` → `SchemaError`; 1 → migrate. `_migrate_1_to_2(conn)` in one `transaction`: create `runs` and `send_attempts` exactly as data-model.md (columns, CHECKs, `UNIQUE(contact_id, campaign, step)`), indexes `idx_runs_kind_started`, `idx_attempts_created`, `idx_attempts_campaign`, then `PRAGMA user_version = 2`.
  - Tests: fresh file → version 2 with all three tables; a v1 file with contacts (built by creating v1 SQL directly) migrates keeping rows and tracking values; version 3 refused; duplicate `(contact_id, campaign, step)` rejected; `pending` with `finished_at` set rejected; `accepted` without `message_id` rejected. Update existing assertions that expect version 1.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_store.py tests/test_import_contacts.py` passes.
- [x] T005 [P] Implement `b2b/campaign.py` with tests in `tests/test_campaign.py` per plan D4, D5 and contracts/files.md
  - `load_campaign(path)`: `tomllib.load` (binary); decode error → `ConfigError(f"{path}: invalid TOML")`. Top-level keys exactly the contract table plus tables `phrases` and `test_sample` with exact key sets; unknown → `ConfigError(f"{path}: unknown key '{key}'")`; missing required → `f"{path}: missing key '{key}'"`; wrong type (bool never counts as int/float) → `f"{path}: '{key}' has the wrong type"`; rule violation → `f"{path}: '{key}' is invalid"`. Keys inside tables are named `phrases.<key>` / `test_sample.<key>` in messages. Defaults from the contract applied when optional keys are absent.
  - Rules: `name` regex; `step == 1`; `template` non-empty string → `Path`; `launch_price_end` is `datetime.date` and not `datetime.datetime`; `timezone` loads with `zoneinfo.ZoneInfo`; integer ranges; `bounce_pause_threshold` int or float with 0 < v < 0.2 → float; `send_days` non-empty, subset of `mon…sun`, no repeats → tuple; `send_start`/`send_end` match `^([01]\d|2[0-3]):[0-5]\d$` → `datetime.time`, end > start. Phrase placeholders via `string.Formatter().parse`: field sets must equal — `greeting_with_name` {nombre}, `greeting_without_name` ∅, `opening_with_city` {empresa, ciudad}, `opening_without_city` {empresa}, `company_fallback` ∅, `opt_out` ∅; conversion or format spec present, or `ValueError` from parsing → invalid. Every string in `phrases` and `test_sample` that `contains_link_or_html` → `f"{path}: '{key}' contains a link or HTML"`.
  - Tests: the real `config/campaign.toml` loads (read-only, no personal data); each error class with a tmp TOML; defaults applied; `contains_link_or_html` true for `https://x`, `www.ejemplo`, `ejemplo.com`, `<b>`, `&nbsp;` and false for `C.A.`, `S.R.L.`, `Nómina Atenea`, `P. D.:`.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_campaign.py` passes.
- [x] T006 [P] Add spec 002 fixtures to `tests/conftest.py`
  - `fake_smtp` → factory `make(script: list[object] | None = None)` returning `(factory, log)`: `factory(settings)` returns a fake with `login(user, password)`, `sendmail(from_addr, to_addrs, msg)`, `quit()`; each `sendmail` pops the next script item — `None` → return `{}`, a dict → return it, an exception instance → raise it; `log.messages` holds `(from_addr, to_addrs, msg)`, `log.logins`, `log.quits` counters; a `login_error` attribute raises on `login` when set.
  - `fake_clock` → object with `now()` (aware UTC datetime, starts `2026-09-14T13:00:00Z` = 09:00 Caracas Monday), `sleep(seconds)` advancing time and appending to `sleeps`.
  - `send_env(tmp_path)` → factory writing a synthetic `.env` (`HOST_EMAIL=smtp.example.com`, `PORT_EMAIL=465`, `USER_EMAIL=usuario-prueba`, `PASS_EMAIL=clave-de-prueba`, `SENDER_EMAIL=remitente@example.com`, `SMTP_FROM_NAME=Ana Remitente`, `TEST_RECIPIENTS=prueba1@example.org,prueba2@example.net`) with overrides; returns the path.
  - `campaign_files(tmp_path)` → factory copying `config/campaign.toml` and the template into `tmp_path/config`, rewriting `template` to the copied path, applying key overrides; returns the campaign path.
  - `contacts_db(db_path)` → factory `make(rows: list[dict]) -> list[int]` inserting synthetic contacts through `store.connect`, `ensure_schema`, `upsert_contacts`, applying optional tracking overrides by SQL; returns contact ids in order.
  - **DoD**: full suite still passes; a throwaway test using each fixture passes (not kept).
- [x] T007 Implement `b2b/template.py` with tests in `tests/test_template.py` per plan D5, D6 and contracts/files.md (depends on T005)
  - `load_template(path, opt_out)`: UTF-8, `\r\n` → `\n`; line 1 must match `^Asunto: (.+)$` → else `ConfigError(f"{path}: line 1 must be 'Asunto: <subject>'")`; line 2 must be empty → `f"{path}: line 2 must be empty"`; body = lines 3+ joined, trailing blank lines removed, must be non-empty → `f"{path}: body is empty"`. Placeholders via `string.Formatter().parse`: subject fields ⊆ `SUBJECT_PLACEHOLDERS`, body fields ⊆ `BODY_PLACEHOLDERS`; parse `ValueError`, conversion or format spec → `f"{path}: invalid braces"`; other names → `f"{path}: unknown placeholder '{name}'"`. `LINK_PATTERN` match in subject or body → `f"{path}: link or domain not allowed in template"`; `HTML_PATTERN` → `f"{path}: HTML not allowed in template"`. `opt_out.strip()` found in body → `f"{path}: remove the opt-out sentence; it is added automatically"`.
  - `display_company(company, fallback)`: strip; empty → `fallback`. If it has a letter and no lowercase letter: for each space-separated word at index i, split into leading chars in `(¿¡"` , middle, trailing chars in `,;:)!?"`; `key` = letters of middle casefolded; `key` in `{"ca": "C.A.", "sa": "S.A.", "srl": "S.R.L.", "cia": "Cía."}` → middle replaced; elif i > 0 and `middle.casefold()` in `{"de","del","la","las","los","y","e","en"}` → lowercase; elif 2 ≤ letter count ≤ 4 and no letter in `aeiouáéíóú` (casefold) → unchanged; else `middle[:1].upper() + middle[1:].lower()`. Otherwise return stripped input unchanged.
  - `first_name(contact_name)`: tokens = `split()`; drop tokens whose letters-only casefold is in `HONORIFICS`; first remaining stripped of trailing `,.`; none, empty, containing a digit or `@` → `""`; has letters and no lowercase → `token[:1].upper() + token[1:].lower()`.
  - `render(...)`: `empresa = display_company(company, phrases.company_fallback)`; `nombre = first_name(contact_name)`; `saludo` = `phrases.greeting_with_name.format(nombre=nombre)` if nombre else `phrases.greeting_without_name`; `apertura` = `phrases.opening_with_city.format(empresa=empresa, ciudad=city.strip())` if `city.strip()` else `phrases.opening_without_city.format(empresa=empresa)`; subject = `template.subject.format(empresa=empresa)`; body = `template.body.format(saludo=saludo, apertura=apertura, remitente=sender_name) + "\n\n" + phrases.opt_out + "\n"`.
  - `rendered_has_link(email)`: `contains_link_or_html(email.subject) or contains_link_or_html(email.body)`.
  - Tests: real template file loads; each load error; `"INVERSIONES EJEMPLO, C.A."` → `"Inversiones Ejemplo, C.A."`; `"DISTRIBUIDORA DE LA COSTA S.R.L."` → `"Distribuidora de la Costa S.R.L."`; `"CORPORACIÓN PDV C.A"` → `"Corporación PDV C.A."`; `"Tienda Mixta, C.A."` unchanged; empty → fallback; `first_name("ING. PEDRO PÉREZ") == "Pedro"`, `first_name("Dra. Luisa Gómez") == "Luisa"`, `first_name("") == ""`, `first_name("ventas2")` → `""`; render with name+city, without name, without city, without company; body ends with `phrases.opt_out + "\n"`; `rendered_has_link` true for company `Tienda.com`.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_template.py` passes.
- [x] T008 [P] Implement `b2b/preflight.py` with tests in `tests/test_preflight.py` per plan D14
  - `make_resolver(timeout)`: `dns.resolver.Resolver()` with `lifetime = timeout`.
  - `check_sender_domain(domain, resolver)`: IDNA-encode (`UnicodeError` → both `unverified`). TXT strings per record = `b"".join(rdata.strings).decode("utf-8", "replace")`. DMARC query `_dmarc.<name>` TXT: `NXDOMAIN`/`NoAnswer` → `missing`; other `dns.exception.DNSException` → `unverified`; a record whose lowercase starts with `v=dmarc1` → `present`, `dmarc_policy` = value of the `p` tag (split on `;`, strip, `tag=value`), else `None`; no such record → `missing`. SPF query `<name>` TXT: `NXDOMAIN`/`NoAnswer` → `missing`; other DNS error → `unverified`; records whose lowercase starts with `v=spf1`: any containing `include:amazonses.com` (case-insensitive) → `includes_ses`, else `present_without_ses`; none → `missing`. Catch `NXDOMAIN` and `NoAnswer` before `DNSException`.
  - Tests with a scripted fake resolver (records with `.strings` tuples of bytes, split strings joined): present with `p=none`, present with `p=reject`, missing via NXDOMAIN, missing via non-DMARC TXT only, unverified via Timeout; SPF includes_ses, present_without_ses, missing, unverified; multi-string TXT record joined.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_preflight.py` passes without network.
- [x] T009 [P] Implement `b2b/send_report.py` with tests in `tests/test_send_report.py` per contracts/cli.md
  - `format_send_summary(s)`: line `f"send_first_email: {s.mode} {s.result}"`; line `f"campaign: {s.campaign} (step {s.step})"`; then `"  " + f"{label + ':':<26}" + value` for, in order: `eligible contacts`, `skipped same company`, `skipped rendered link`, `selected`, `previewed`, `test emails sent`, `accepted`, `permanent rejections`, `temporary failures`, `unknown outcome` (ints as `str`), `campaign bounce rate` = `f"{(s.bounced / s.bounce_base * 100) if s.bounce_base else 0:.1f}% ({s.bounced} of {s.bounce_base})"`, `DMARC` = `s.dmarc`, `SPF` = `s.spf`, `forced no DMARC` = `"yes"`/`"no"`, `stop reason`, `next window opens`; then `f"preview: {s.preview_path}"`. Joined with `\n`, one trailing `\n`.
  - Tests: golden string for a send summary (bounce 1 of 40 → `2.5% (1 of 40)`); zero base → `0.0% (0 of 0)`; trailing newline.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_send_report.py` passes.
- [x] T010 Implement `b2b/mailer.py` with tests in `tests/test_mailer.py` per plan D12, D13 (depends on T005, T006, T007)
  - `load_sender_settings`: `dotenv_values(env_path)` only; keys and rules from contracts/files.md; errors `ConfigError(f"{env_path}: missing {KEY}")` / `f"{env_path}: invalid {KEY}"`; `SENDER_EMAIL` and each test recipient checked with `b2b.emails.validate(normalize_token(...))`; `SMTP_FROM_NAME` rejected if `contains_link_or_html`; `PORT_EMAIL` must be 465 or 587.
  - `default_smtp_factory(settings)`: 465 → `smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())`; 587 → `smtplib.SMTP(host, port, timeout=30)` then `starttls(context=...)`.
  - `build_message`, `check_login`, `send_email` exactly per D12, including the outcome table and `stop` = `error_kind in STOP_KINDS`; never keep SMTP response text; `quit()` errors ignored.
  - Tests with `fake_smtp`: headers (From name encoded, To bare, Reply-To, Date, Message-ID domain), single `text/plain; charset="utf-8"` part with quoted-printable, accents round-trip; accepted; 550 recipient refused → permanent; 450 recipient → temporary not stop; sender refused → stop; 454 data → `provider_throttled`; 554 "Message rejected: Email address is not verified" → `identity_not_verified`; 554 other → `message_rejected`; disconnect during `sendmail` → `unknown` `connection_lost`; login error → `authentication_failed`; `repr(settings)` excludes the password; missing/invalid `.env` keys.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_mailer.py` passes.

**Checkpoint**: config, template, preflight, report, mailer and schema v2 ready.

---

## Phase 3: User Story 1 — Preview the first email without sending (Priority: P1) 🎯 MVP

**Goal**: default command writes every email the campaign would send to a preview file and sends
nothing.

**Independent Test**: synthetic database + real config copies; default mode writes the preview,
leaves every table unchanged, opens no socket, prints counts only.

- [x] T011 [P] [US1] Implement `b2b/eligibility.py` with tests in `tests/test_eligibility.py` per plan D8 (depends on T004, T006)
  - One SQL query for candidates (conditions D8), then Python: group by `company_key`, pick by (completeness desc, `source_year` desc, `source_row` asc, `email` asc), order chosen by (`source_year` desc, `id` asc). `eligible` = candidate count; `skipped_same_company` = candidates − chosen.
  - Tests: each exclusion (contacted, bounced, responded, opted out, generic, attempt in campaign, `unknown` attempt in another campaign, company with an `accepted` attempt in campaign); one per company with tie-breaks; 2020 before 2009 ordering; a `temporary_failure` attempt of another contact at the company does not exclude the company.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_eligibility.py` passes.
- [x] T012 [P] [US1] Implement `b2b/preview.py` with tests in `tests/test_preview.py` per contracts/files.md (depends on T005, T007)
  - `write_preview`: create dir; local = `generated_at.astimezone(ZoneInfo(campaign.timezone))`; name `f"{campaign.name}-{local:%Y%m%d-%H%M%S}.txt"`, adding `-2`, `-3`… before `.txt` if it exists; content exactly the contract layout (`Generated: {local:%Y-%m-%d %H:%M} {campaign.timezone}`), each email block `===== {i} of {n} =====`, `To:`, `Subject:`, blank line, body; UTF-8.
  - Tests: layout golden string for two synthetic emails; name collision suffix; zero emails still writes the header with `Emails: 0`.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_preview.py` passes.
- [x] T013 [US1] Create `b2b/send_first_email.py` with argparse, shared setup and preview mode per plan D9, D15, D16 and contracts/cli.md (depends on T004, T005, T007, T009, T011, T012)
  - Options per contract; `_Parser.error` → exit 1 via stderr line; `--force-no-dmarc` outside send → exit 1. Setup: `load_campaign`, `load_template(campaign.template, phrases.opt_out)`, `launch_price_passed` check using `now()` (pacing, T018 — until then compute today in the campaign zone inline and replace when T018 lands), `SMTP_FROM_NAME` from `load_sender_settings(require_test_recipients=False)` for `{remitente}`; DB `connect` + `ensure_schema`. Preview: `select_recipients`, render each, drop `rendered_has_link` (count), take first `batch_limit`, `write_preview`, summary `result = "done"` (or `nothing_to_send` when zero selected, still writing the file). Exit codes and error lines per contract; `if __name__ == "__main__": raise SystemExit(main())`.
  - **DoD**: `.venv/bin/python -m b2b.send_first_email --help` exits 0; T014 passes.
- [x] T014 [US1] Write preview end-to-end tests in `tests/test_send_first_email.py` (depends on T013)
  - US1-1 file written, tables unchanged (row dumps of `contacts`, `runs`, `send_attempts` equal before/after), `fake_smtp` never called; US1-2/3/4 rendered text in the file; US1-5 template with link → exit 1; launch-price date past → exit 1; stdout/stderr contain no synthetic address, name, company or city; `--force-no-dmarc` with preview → exit 1; schema newer than 2 → exit 2.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_send_first_email.py` passes.

**Checkpoint**: MVP — the operator can read exactly what would be sent.

---

## Phase 4: User Story 2 — Test send to own addresses (Priority: P1)

**Goal**: synthetic sample emails reach the operator's test mailboxes; the database is untouched.

**Independent Test**: test mode with `fake_smtp` delivers only to `TEST_RECIPIENTS`, `[PRUEBA] `
subjects, synthetic sample text, no rows written.

- [x] T015 [US2] Add test mode to `b2b/send_first_email.py` per plan D9, D17 (depends on T008, T010, T013)
  - `load_sender_settings(require_test_recipients=True)`; render up to `test_sample_count` variants from `test_sample` in order: full, without name, without city (contact_id `None`, recipients round-robin over `test_recipients`), subject prefixed `[PRUEBA] `; send each with `send_email`; any outcome other than `accepted` → stop, summary `result = "stopped"`, exit 4; DMARC/SPF via `check_sender_domain(domain of sender, resolver or make_resolver())` shown only. No `select_recipients`, no row writes.
  - **DoD**: T016 passes.
- [x] T016 [US2] Add test-mode tests to `tests/test_send_first_email.py` (depends on T015)
  - US2-1 recipients and subjects; bodies contain only `test_sample` values; US2-2 table dumps unchanged; missing `TEST_RECIPIENTS` → exit 1; SMTP 454 → exit 4 with stop reason; DMARC missing does not block test mode.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_send_first_email.py` passes.

---

## Phase 5: User Story 3 — Throttled production send (Priority: P1)

**Goal**: confirmed batches are sent one at a time, recorded before each send, paced, and stopped
by the guards.

**Independent Test**: production mode with fake SMTP, fake clock and synthetic contacts proves
confirmation, at-most-once sending across a simulated crash, pacing, database updates and every
stop rule.

- [x] T017 [P] [US3] Implement `b2b/tracking.py` with tests in `tests/test_tracking.py` per plan D10, D11 and data-model.md (depends on T004, T006, T010)
  - `send_lock`: open `<db>.send.lock` (create), `fcntl.flock(LOCK_EX | LOCK_NB)`, `BlockingIOError` → `SendLockBusy`; unlock and close on exit. `recover_pending`: in one transaction set every `pending` → `unknown`, `error_kind = 'interrupted'`, `finished_at = now`; return count. `batch_hold_satisfied`, `start_run`, `finish_run`, `record_pending` (own committed transaction), `record_outcome` (one transaction: attempt row update + contact update per data-model transitions), `attempts_in_last_hour`, `campaign_bounce`, `bounce_exceeded` (`base >= min_sends and bounced / base > threshold`).
  - Tests: lock busy from a second `send_lock`; recovery; every outcome's contact effect (bounced not overwritten when already 1); hold with no runs / production without inbox / inbox finished before / after / crashed production run using `started_at`; bounce math at 19 and 20 sends; rolling hour boundaries.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_tracking.py` passes.
- [x] T018 [P] [US3] Implement `b2b/pacing.py` with tests in `tests/test_pacing.py` per plan D7, D11 (depends on T005)
  - `local_now` → `moment.astimezone(ZoneInfo(campaign.timezone))`; `window_contains`: local weekday name (`mon`…`sun`) in `send_days` and `send_start <= local.time() < send_end`; `next_window_start`: the earliest local datetime ≥ moment inside the window (same day start if before start, else following allowed day at `send_start`), returned in UTC; `next_interval` = `3600 / hourly_cap * rng.uniform(0.8, 1.2)`; `cap_wait_seconds`: 0 when `count < hourly_cap`, else seconds until `oldest_created_at + 3600 s` (≥ 0); `launch_price_passed`: `local_now(...).date() > launch_price_end`.
  - Tests with fixed datetimes (Friday 16:59 → inside; 17:00 → outside, next Monday 08:00 Caracas; Saturday → Monday), interval bounds with a seeded `Random`, cap wait, date boundary at local midnight.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_pacing.py` passes.
- [x] T019 [US3] Add send mode (gates and loop) to `b2b/send_first_email.py` per plan D10, D11 (depends on T015, T017, T018)
  - Gates in D10 order except the DMARC gate (7), which T021 adds: lock (exit 3), config/credentials (exit 1), schema + `recover_pending`, batch hold (exit 3), bounce pre-check (exit 3), `check_login` (exit 1), window (exit 0, `next_window` in summary), selection (exit 0 `nothing_to_send`), confirmation via `ask` (exit 3 unless exact campaign name), `start_run`. Loop per D11 using `sleep`/`now`/`rng` injections; `finish_run` in `finally` with the stop reason (`interrupted` on `KeyboardInterrupt`, then exit 130). Exit 0 on `batch_complete`, 4 on any other stop. Summary counts from outcomes and `campaign_bounce`.
  - **DoD**: T020 passes; T014/T016 still pass.
- [x] T020 [US3] Add production tests to `tests/test_send_first_email.py` (depends on T019)
  - US3-1 confirmation text printed and wrong answer → exit 3, no rows; US3-2 accepted updates and attempt rows; US3-3 excluded contacts never selected; US3-4 550 → bounced; US3-5 bounce threshold stops before the next email (pre-seed bounced attempts); US3-6 crash simulation: fake SMTP raises `KeyboardInterrupt` after recording → exit 130, rerun marks `unknown`, contact not re-sent; US3-7 cap and batch limit with fake clock (sleeps recorded, never more than cap attempts in any rolling hour); window closing mid-batch → `window_closed`; launch price passing mid-batch → `launch_price_ended`; three consecutive 450s → `temporary_failures`; 454 → `provider_throttled`; second batch refused until an `inbox` run row finishes (FR-018); concurrent lock → exit 3; outputs contain no synthetic contact values.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_send_first_email.py` passes.

**Checkpoint**: production sending complete apart from the DMARC gate.

---

## Phase 6: User Story 4 — Deliverability preflight (Priority: P2)

**Goal**: production refuses to start without DMARC unless forced, and records the override.

**Independent Test**: fake resolver with and without a DMARC record; production refuses or, with
`--force-no-dmarc`, confirms and records `forced_no_dmarc = 1`.

- [x] T021 [US4] Add the DMARC gate and `--force-no-dmarc` handling to `b2b/send_first_email.py` per plan D10 gate 7 and FR-015 (depends on T008, T019)
  - After `check_login`: `check_sender_domain`; `dmarc != "present"` and no force → error line from the contract, exit 3; with force → continue; confirmation block shows DMARC, SPF and forced flag; `start_run(forced_no_dmarc=...)`; summary DMARC/SPF values.
  - **DoD**: T022 passes; all earlier send tests still pass (their fixtures supply a resolver with DMARC present).
- [x] T022 [US4] Add preflight tests to `tests/test_send_first_email.py` (depends on T021)
  - US4-1 missing DMARC → exit 3, no run row; unverified DMARC → exit 3; US4-2 present → summary shows `present` and SPF status; force → run row `forced_no_dmarc = 1`, confirmation shows `forced no DMARC: yes`.
  - **DoD**: `.venv/bin/python -m pytest -q` (full suite) passes.

**Checkpoint**: feature complete on synthetic data.

---

## Phase 7: Polish & Operations

- [x] T023 Run the full suite `.venv/bin/python -m pytest -q` and fix failures through the loop
  - **DoD**: all tests pass (spec 001 and 002); no `data/previews/` or `.send.lock` created under the project by tests.
- [x] T024 [P] Update docs: `docs/CHANGELOG.md` (feature entry, files added) and `.claude/CLAUDE.md` (Stack: command implemented; TEST: send tests use fake SMTP/clock/resolver)
  - **DoD**: both updated; no contact values or credentials.
- [x] T025 Real preview per `specs/002-first-email-send/quickstart.md` §2 (needs explicit user authorization — reads the contact database)
  - **DoD**: exit 0; counts reported; operator reads at least 10 emails in the preview file and approves the wording.
- [x] T026 Test send per `specs/002-first-email-send/quickstart.md` §3 (needs explicit user authorization — connects to SES) after T003
  - **DoD**: exit 0, `test emails sent` = `test_sample_count`; operator confirms inbox placement on two providers, sender name, reply address and accents (SC-005).
- [ ] T027 [P] Operator publishes DMARC for the sender domain (manual DNS change) or decides to use `--force-no-dmarc` for the first batch
  - **DoD**: operator states the decision; Claude re-checks `_dmarc` with `dig` if published.
- [ ] T028 First production batch per `specs/002-first-email-send/quickstart.md` §4 — run by the operator in their own terminal (`tmux`), who types the confirmation (needs explicit user authorization)
  - **DoD**: summary pasted or described by the operator; `stop reason` known.
- [ ] T029 Post-batch database checks per `specs/002-first-email-send/quickstart.md` §4 (counts only)
  - **DoD**: schema 2; contacted = accepted attempts; zero companies emailed twice in the campaign; run row present with the right `forced_no_dmarc`.
- [ ] T030 Verify the batch hold per `specs/002-first-email-send/quickstart.md` §5 (needs explicit user authorization — opens the production command against the real database)
  - **DoD**: `--mode send` exits 3 with the batch-hold error before any confirmation prompt.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup**: T001, T002, T003 in parallel; T003 only blocks T026.
- **Foundational**: T004, T005, T006, T008, T009 in parallel; T007 after T005; T010 after T005, T006, T007.
- **US1**: T011 (after T004, T006) and T012 (after T005, T007) in parallel; T013 after T001, T002, T009, T011, T012; T014 after T013.
- **US2**: T015 after T008, T010, T013; T016 after T015.
- **US3**: T017 (after T004, T006, T010) and T018 (after T005) in parallel; T019 after T015, T017, T018; T020 after T019.
- **US4**: T021 after T008, T019; T022 after T021.
- **Polish**: T023 after T022; T024 alongside; T025 after T023; T026 after T025 and T003; T027 any time; T028 after T026 and T027 (and spec 001 T029 recommended); T029 after T028; T030 after T029.

### Story order

```text
Setup ─► Foundational ─► US1 preview ─► US2 test send ─► US3 production ─► US4 DMARC gate ─► Polish/operations
```

All stories extend the same command file, so they run in sequence; the modules inside each phase
are parallel.

---

## Parallel Examples

```text
# Setup
T001 config/campaign.toml | T002 template | T003 operator .env key

# Foundational (first wave)
T004 store migration | T005 campaign.py | T006 conftest fixtures | T008 preflight.py | T009 send_report.py
# second wave
T007 template.py → T010 mailer.py

# US1
T011 eligibility.py | T012 preview.py → T013 → T014

# US3
T017 tracking.py | T018 pacing.py → T019 → T020
```

---

## Implementation Strategy

1. Setup + Foundational.
2. US1 (T011–T014) → **stop and validate**: the preview is the MVP and the operator reviews real
   wording (T025) before anything can send.
3. US2 → real test send (T026) and inbox placement check.
4. US3 + US4 → full suite (T023).
5. Operations: DMARC decision (T027), first batch by the operator (T028), checks (T029, T030),
   then the manual inbox check before any second batch.

---

## Delegation Classification

| Task | Executor | Reason |
|------|----------|--------|
| T001 | CLAUDE | campaign pacing and thresholds (send-path configuration) |
| T002 | DEEPSEEK | literal template text from the contract |
| T003 | OPERATOR | personal addresses in `.env` |
| T004 | CLAUDE | schema migration guarding the tracker |
| T005 | DEEPSEEK | config parsing and validation, fully pinned |
| T006 | CLAUDE | test harness for the send path |
| T007 | DEEPSEEK | template loading and rendering, fully pinned |
| T008 | DEEPSEEK | DNS TXT parsing, fully pinned, no credentials |
| T009 | DEEPSEEK | summary formatting, pinned |
| T010 | CLAUDE | credentials, SMTP connection, outcome classification |
| T011 | CLAUDE | recipient selection |
| T012 | DEEPSEEK | preview file writer, pinned |
| T013 | CLAUDE | command orchestration |
| T014 | CLAUDE | end-to-end safety tests |
| T015 | CLAUDE | sending path (test mode) |
| T016 | CLAUDE | end-to-end tests |
| T017 | CLAUDE | at-most-once tracking, lock, batch hold |
| T018 | CLAUDE | throttling and send window |
| T019 | CLAUDE | production gates and send loop |
| T020 | CLAUDE | production safety tests |
| T021 | CLAUDE | production gate |
| T022 | CLAUDE | gate tests |
| T023–T026 | CLAUDE | test run, docs, authorized real runs |
| T027 | OPERATOR | DNS change |
| T028 | OPERATOR | production run with typed confirmation |
| T029–T030 | CLAUDE | counts-only checks, authorized refusal check |

**Totals**: 6 DEEPSEEK, 21 CLAUDE, 3 OPERATOR.

## Notes

- No git: list changed files in each task report; CHANGELOG entry per change.
- Claude never types the production confirmation and never pipes it into the command (Constitution V).
- Nothing in this feature reads `contactos/`; real runs read `data/b2b.sqlite3` and `.env`.
