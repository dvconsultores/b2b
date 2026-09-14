---

description: "Task list for 001-clean-contact-list"
---

# Tasks: Clean Contact Database

**Input**: Design documents from `specs/001-clean-contact-list/`

**Prerequisites**: plan.md (D1–D15), spec.md (US1–US4), research.md, data-model.md,
contracts/cli.md, contracts/files.md, quickstart.md

**Tests**: Required. The constitution (Development Workflow) and `.claude/CLAUDE.md` (TEST step)
make passing pytest suites part of every task's definition of done. Tests use synthetic data
only (`example.com`, `example.org`, `example.net`) and never read `contactos/`, `.env` or
`data/`.

**Organization**: Setup → Foundational → one phase per user story in spec order → Polish.
Each module task creates the module and its test file together (≤ 2 files) so it can be
delegated as one unit.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 from spec.md
- Indented lines under a task give the pinned interface and the **DoD**; they are part of the
  task.

## Shared interface (pinned — all tasks)

Names below are the only public names modules may export or import from each other.
Dataclasses are `@dataclass(frozen=True)` unless marked mutable.

```python
# b2b/__init__.py
class InputError(Exception): ...     # missing file/sheet header; message names file, sheet, headers only
class ConfigError(Exception): ...    # bad config file; message names file and line numbers only

# b2b/sources.py
@dataclass(frozen=True)
class SourceRow:
    source_file: str        # base name, e.g. "ClientesFebrero2020.xls"
    source_sheet: str
    source_row: int         # 1-based spreadsheet row
    source_year: int        # 2020 clients, 2009 yearbook
    company: str            # trimmed, internal whitespace collapsed
    contact_name: str       # same rules; "" for clients
    city_raw: str           # same rules
    tax_id_raw: str         # same rules; "" for yearbook
    area: str               # same rules; "" for yearbook
    email_raw: str          # cell_text() only — NOT trimmed or collapsed
    company_contains_at: bool
@dataclass(frozen=True)
class SourceRead:
    source_file: str
    source_year: int
    rows: list[SourceRow]
    skipped_sheets: list[str]
CLIENT_HEADERS = ("RIF", "NOMBRE", "CIUDAD", "MAIL", "AREA")
YEARBOOK_HEADERS = ("EMPRESA", "CONTACTO", "CORREO", "CIUDAD")
def cell_text(value: object) -> str
def rows_from_sheet(kind: Literal["clients", "yearbook"], source_file: str, sheet_name: str,
                    raw_rows: list[list[object]]) -> list[SourceRow] | None   # None = skipped
def read_clients(path: Path) -> SourceRead
def read_yearbook(path: Path) -> SourceRead

# b2b/emails.py
@dataclass(frozen=True)
class EmailExtraction:
    candidates: list[str]               # valid normalized addresses, in cell order, no repeats
    invalid: list[tuple[str, str]]      # (original token, reason)
def normalize_token(token: str) -> str
def validate(address: str) -> str | None        # None = valid, else "empty" | "invalid_format" | "non_ascii_local_part"
def extract(cell: str) -> EmailExtraction
def domain_of(address: str) -> str

# b2b/domains.py
DomainStatus = Literal["accepts", "domain_not_found", "no_mail_server", "null_mx", "unverified"]
REJECT_STATUSES: frozenset[str] = frozenset({"domain_not_found", "no_mail_server", "null_mx"})
def make_dns_checker(timeout: float = 3.0, resolver: object | None = None) -> Callable[[str], DomainStatus]
def check_domains(domains: Iterable[str], checker: Callable[[str], DomainStatus],
                  workers: int = 16) -> dict[str, DomainStatus]

# b2b/companies.py
def name_key(company: str) -> str
def normalize_tax_id(raw: str) -> str
def is_valid_rif(normalized: str) -> bool
def stored_tax_id(raw: str) -> str
def assign_company_keys(items: Sequence[tuple[str, str, str]]) -> list[str]   # (company, tax_id_raw, email)

# b2b/cities.py
@dataclass(frozen=True)
class CityMap:
    canonical_by_key: dict[str, str]
def match_key(value: str) -> str
def title_case(value: str) -> str
def load_city_map(path: Path) -> CityMap
def normalize_city(raw: str, city_map: CityMap) -> tuple[str, bool]   # (stored value, needs_review)
def aggregate_unmapped_cities(raw_values: Iterable[str]) -> list[ReviewItem]

# b2b/classify.py
def load_role_words(path: Path) -> frozenset[str]
def reduce_local_part(local: str) -> str
def classify(address: str, role_words: frozenset[str]) -> Literal["personal", "generic"]

# b2b/merge.py
@dataclass(frozen=True)
class Candidate:
    row: SourceRow
    email: str
    order: int
    company_key: str
@dataclass(frozen=True)
class Group:
    winner: Candidate
    merged: list[Candidate]
    conflict: bool
def completeness(row: SourceRow) -> int
def group_candidates(candidates: Sequence[Candidate]) -> list[Group]

# b2b/store.py
SCHEMA_VERSION = 1
class SchemaError(Exception): ...
@dataclass(frozen=True)
class ContactValues:
    email: str; company: str; company_key: str; contact_name: str; city: str; tax_id: str
    area: str; classification: str; source_file: str; source_sheet: str; source_row: int
    source_year: int
@dataclass            # mutable
class UpsertResult:
    new: list[str]; updated: list[str]; unchanged: list[str]
def utc_now() -> str
def connect(path: Path) -> sqlite3.Connection
def ensure_schema(conn: sqlite3.Connection) -> None
@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]
def existing_emails(conn: sqlite3.Connection) -> set[str]
def upsert_contacts(conn: sqlite3.Connection, values: Sequence[ContactValues], now: str) -> UpsertResult
def count_contacts(conn: sqlite3.Connection) -> int

# b2b/reports.py
@dataclass(frozen=True)
class SourceRef:
    source_file: str = ""; source_sheet: str = ""; source_row: int | None = None
@dataclass(frozen=True)
class RejectedRow:
    ref: SourceRef; email_raw: str; reason: str
@dataclass(frozen=True)
class ReviewItem:
    type: str; ref: SourceRef; detail: str; count: int = 1
@dataclass            # mutable
class SourceCounts:
    source_file: str; source_year: int | None
    sheets_skipped: list[str] = field(default_factory=list)
    rows_read: int = 0; split_extra: int = 0; format_rejected: int = 0; merged: int = 0
    conflicts: int = 0; new: int = 0; existing_updated: int = 0; existing_unchanged: int = 0
    domain_rejected: int = 0; unverified: int = 0; personal: int = 0; generic: int = 0
    missing_city: int = 0; distinct_companies: int = 0
def reconciles(c: SourceCounts) -> bool
def total_counts(per_source: Sequence[SourceCounts], distinct_companies: int) -> SourceCounts
def stage_rejects(reports_dir: Path, rows: Sequence[RejectedRow]) -> Path
def stage_review(reports_dir: Path, items: Sequence[ReviewItem]) -> Path
def publish(staged: Path, final: Path) -> None
def discard(staged: Path) -> None
def format_summary(per_source: Sequence[SourceCounts], total: SourceCounts, not_in_sources: int,
                   db_path: Path, contacts: int, rejects_path: Path, rejects_rows: int,
                   review_path: Path, review_rows: int) -> str

# b2b/import_contacts.py
def main(argv: list[str] | None = None, checker: Callable[[str], DomainStatus] | None = None) -> int
```

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dependencies, package, operator-editable configuration

- [x] T001 Create `requirements.txt` and `requirements-dev.txt` at the project root per plan D2
  - `requirements.txt`: `xlrd==2.0.2`, `openpyxl==3.1.5`, `dnspython==2.8.0`, `python-dotenv==1.2.3`, one per line, in that order. `requirements-dev.txt`: `-r requirements.txt` then `pytest==9.1.1`.
  - **DoD**: both files exist with exactly those lines.
- [x] T002 Install dependencies into `.venv` with `.venv/bin/python -m pip install -r requirements-dev.txt` (needs implementation authorization)
  - **DoD**: `.venv/bin/python -m pip list` shows the five pinned versions; `.venv/bin/python -m pytest --version` prints 9.1.1.
- [x] T003 [P] Create `b2b/__init__.py` defining `InputError` and `ConfigError` (see Shared interface), each with a one-line docstring and nothing else
  - **DoD**: `.venv/bin/python -c "import b2b; b2b.InputError; b2b.ConfigError"` exits 0.
- [x] T004 [P] Create `config/role_words.txt` per plan D6 and contracts/files.md
  - First line `# Role words: local parts reduced to these are classified generic (spec 001, plan D6)`, then the D6 list one word per line in the order given in the plan.
  - **DoD**: 46 non-comment lines, all matching `^[a-z]+$`.
- [x] T005 [P] Create `config/cities.csv` per plan D8 and contracts/files.md
  - UTF-8 without BOM, header `variant,canonical`, then these rows (public city names only): `caracas,Caracas` · `ccs,Caracas` · `maracaibo,Maracaibo` · `valencia,Valencia` · `barquisimeto,Barquisimeto` · `maracay,Maracay` · `puerto la cruz,Puerto La Cruz` · `barcelona,Barcelona` · `lecheria,Lechería` · `puerto ordaz,Puerto Ordaz` · `ciudad guayana,Ciudad Guayana` · `san cristobal,San Cristóbal` · `merida,Mérida` · `maturin,Maturín` · `cumana,Cumaná` · `ciudad bolivar,Ciudad Bolívar` · `los teques,Los Teques` · `guarenas,Guarenas` · `guatire,Guatire` · `punto fijo,Punto Fijo` · `coro,Coro` · `acarigua,Acarigua` · `barinas,Barinas` · `san felipe,San Felipe` · `porlamar,Porlamar` · `valera,Valera` · `cabimas,Cabimas` · `puerto cabello,Puerto Cabello` · `la victoria,La Victoria` · `san juan de los morros,San Juan de los Morros`.
  - **DoD**: 31 lines (header + 30), no two variants share a D8 match key.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: test harness, source reading, shared report entities, database schema

**⚠️ CRITICAL**: no user story work can begin until this phase is complete

- [x] T006 Create `tests/conftest.py` per plan D14 (depends on T002)
  - Autouse fixture `_no_network(monkeypatch)`: replace `socket.socket` and `dns.resolver.Resolver.resolve` with functions raising `RuntimeError("network disabled in tests")`.
  - Fixture `fake_checker` → factory `make(statuses: dict[str, str]) -> Callable[[str], str]` returning `statuses.get(domain, "accepts")`.
  - Fixture `yearbook_xlsx(tmp_path)` → factory `make(sheets: dict[str, list[list[object]]], name="Year Book 2009.xlsx") -> Path` writing a workbook with openpyxl (sheet order = dict order; a sheet with `[]` stays empty).
  - Fixture `stub_xls(monkeypatch, tmp_path)` → factory `make(sheets: dict[str, list[list[object]]], name="ClientesFebrero2020.xls") -> Path` that creates an empty file at `tmp_path/name` and patches `xlrd.open_workbook` to return an object whose `.sheets()` yields objects with `.name`, `.nrows`, `.row_values(i)`.
  - Fixture `db_path(tmp_path) -> Path` = `tmp_path / "data" / "b2b.sqlite3"` (not created).
  - **DoD**: `.venv/bin/python -m pytest -q` collects with no errors; a throwaway test calling `socket.socket()` fails with the RuntimeError (not kept in the suite).
- [x] T007 Implement source reading in `b2b/sources.py` with tests in `tests/test_sources.py` per plan D3 (depends on T003, T006)
  - `cell_text`: `None` → `""`; `float` with integral value → `str(int(v))`; other `float` → `repr`-free `str(v)`; `datetime`/`date` → `.isoformat()`; `bool` → `"TRUE"`/`"FALSE"`; else `str(value)`.
  - `rows_from_sheet`: a row is blank when every `cell_text(...).strip()` is empty. Return `None` when the sheet has no non-blank rows or only row 1 is non-blank. Otherwise row 1 is the header: compare `cell_text(h).strip().upper()`; missing required headers (`CLIENT_HEADERS` or `YEARBOOK_HEADERS`) → `InputError(f"{source_file} sheet '{sheet_name}': missing header(s) {', '.join(missing)}")`. Build one `SourceRow` per non-blank data row (rows shorter than the header count as empty cells). Column mapping — clients: company=NOMBRE, contact_name="", city_raw=CIUDAD, tax_id_raw=RIF, area=AREA, email_raw=MAIL, source_year 2020; yearbook: company=EMPRESA, contact_name=CONTACTO, city_raw=CIUDAD, tax_id_raw="", area="", email_raw=CORREO, source_year 2009. Descriptive fields = `" ".join(cell_text(v).split())`; `email_raw = cell_text(v)`; `company_contains_at = "@" in company`.
  - `read_clients(path)`: missing file → `InputError(f"{path}: file not found")`; `xlrd.open_workbook(str(path))`; sheets in workbook order; `raw_rows = [sheet.row_values(i) for i in range(sheet.nrows)]`; skipped sheet names collected in order.
  - `read_yearbook(path)`: missing file → same error; `openpyxl.load_workbook(path, read_only=True, data_only=True)`; `raw_rows = [list(r) for r in ws.iter_rows(values_only=True)]`; close the workbook.
  - Tests: header-only sheet and empty sheet skipped; missing header raises with file/sheet/header names; blank rows ignored and row numbers kept; integral floats; whitespace collapse on descriptive fields but not on `email_raw`; column mapping for both kinds using `stub_xls` and `yearbook_xlsx`.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_sources.py` passes.
- [x] T008 [P] Implement report entities and counting helpers in `b2b/reports.py` with tests in `tests/test_reports.py` (depends on T006)
  - Only `SourceRef`, `RejectedRow`, `ReviewItem`, `SourceCounts`, `reconciles`, `total_counts` in this task.
  - `reconciles(c)`: `c.rows_read + c.split_extra == c.format_rejected + c.merged + c.new + c.existing_updated + c.existing_unchanged + c.domain_rejected + c.unverified`.
  - `total_counts(per_source, distinct_companies)`: `source_file="total"`, `source_year=None`, `sheets_skipped` concatenated in order, every other int field summed except `distinct_companies`, which takes the argument.
  - **DoD**: tests cover a reconciling and a non-reconciling `SourceCounts` and `total_counts`; `.venv/bin/python -m pytest -q tests/test_reports.py` passes.
- [x] T009 [P] Implement the database schema layer in `b2b/store.py` with tests in `tests/test_store.py` per plan D10 and data-model.md (depends on T006)
  - Only `SCHEMA_VERSION`, `SchemaError`, `utc_now`, `connect`, `ensure_schema`, `transaction` in this task.
  - `utc_now()` → `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`. `connect(path)` creates the parent directory, opens with `isolation_level=None`, sets `row_factory = sqlite3.Row`, runs `PRAGMA foreign_keys = ON`. `ensure_schema`: `user_version` 0 with no `contacts` table → create the `contacts` table exactly as data-model.md (columns, defaults, CHECKs including the table-level pair checks) plus `CREATE INDEX idx_contacts_company_key ON contacts(company_key)` and `PRAGMA user_version = 1`, inside one transaction; version 1 → no-op; greater than 1 → `SchemaError(f"{path}: schema version {v} is newer than this tool (1)")` using `PRAGMA database_list` for the path. `transaction(conn)`: `BEGIN IMMEDIATE`; `COMMIT` on success; `ROLLBACK` and re-raise on any `BaseException`.
  - Tests: fresh file gets version 1 and all columns; second `ensure_schema` is a no-op; version 2 raises `SchemaError`; CHECKs reject `bounced=1` with NULL `bounced_at` and `times_contacted=1` with NULL `last_contacted_at`; an exception inside `transaction` leaves no inserted row.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_store.py` passes.

**Checkpoint**: sources read, schema exists, test harness blocks the network.

---

## Phase 3: User Story 1 — Database of addresses valid to be sent (Priority: P1) 🎯 MVP

**Goal**: one command turns both source files into a database of unique, normalized addresses
whose domain accepts mail, plus rejects and review reports.

**Independent Test**: `main([...synthetic paths...], checker=fake)` on `stub_xls` + `yearbook_xlsx`
inputs with case/space defects, invalid cells, repeats, empty sheets, two-address cells and
failing domains; the database and `rejects.csv` / `review.csv` match the expected rows; no
network used.

- [x] T010 [P] [US1] Implement address extraction and validation in `b2b/emails.py` with tests in `tests/test_emails.py` per plan D4 (depends on T006)
  - `normalize_token`: remove every character where `str.isspace()`; lowercase; remove a leading `mailto:`; `strip('.,;:<>()[]"\'')`.
  - `validate(address)` returns the first failing reason in D4 order (`empty`, `invalid_format`, `non_ascii_local_part`, then local-part length/regex and domain rules → `invalid_format`), or `None`.
  - `extract(cell)`: if `cell.count("@") <= 1` → one token `normalize_token(cell)` (empty cell gives token `""` → reason `empty`); else tokens = parts of `re.split(r"[;,/\s]+", cell)` containing `@`, each normalized. Valid tokens go to `candidates` (first occurrence only); invalid ones to `invalid` as `(original token, reason)` — for the single-token case the original token is `cell`.
  - `domain_of(address)` → text after the last `@`.
  - Tests: `"  Ana.Perez@Example.COM "` → `ana.perez@example.com`; inner spaces removed; `mailto:` and `<...>` stripped; empty; no `@`; two `@` in one token; non-ASCII local part; label starting with `-`; numeric TLD; 65-char local part; Unicode domain `ejemplo@compañía.example` accepted; `"a@example.com; b@example.org"` → two candidates; `"a@example.com / bad@"` → one candidate + one invalid.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_emails.py` passes.
- [x] T011 [P] [US1] Implement the DNS domain checker in `b2b/domains.py` with tests in `tests/test_domains.py` per plan D5 (depends on T006)
  - `make_dns_checker(timeout, resolver)`: `resolver = resolver or dns.resolver.Resolver()`; set `resolver.lifetime = timeout`. The returned `check(domain)`: `name = domain.encode("idna").decode("ascii")` (`UnicodeError` → `"unverified"`); `resolver.resolve(name, "MX")`: records all with `preference == 0` and `exchange.to_text() == "."` → `"null_mx"`; any other answer → `"accepts"`; `dns.resolver.NXDOMAIN` → `"domain_not_found"`; `dns.resolver.NoAnswer` → try `"A"` then `"AAAA"`: answer → `"accepts"`, `NXDOMAIN` → `"domain_not_found"`, `NoAnswer` → next type, any other `dns.exception.DNSException` → `"unverified"`; both `NoAnswer` → `"no_mail_server"`; any other `dns.exception.DNSException` on MX → `"unverified"`. Catch `NXDOMAIN` and `NoAnswer` before `DNSException`.
  - `check_domains`: unique domains sorted; `ThreadPoolExecutor(max_workers=workers)`; a checker exception for a domain → `"unverified"`; return dict in sorted order.
  - Tests use a fake resolver object with `resolve(name, rdtype)` scripted per `(name, rdtype)`: MX answer, null MX, NXDOMAIN, NoAnswer→A, NoAnswer→AAAA, NoAnswer everywhere, `dns.exception.Timeout`, `dns.resolver.NoNameservers`, IDNA name passed to the resolver for a Unicode domain; `check_domains` dedupes, sorts and maps a raising checker to `"unverified"`.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_domains.py` passes without network.
- [x] T012 [P] [US1] Implement company keys in `b2b/companies.py` with tests in `tests/test_companies.py` per plan D7 (depends on T006)
  - `name_key`: NFKD, drop `unicodedata.combining` chars, `casefold`, `re.sub(r"[^0-9a-z]+", " ", ...)`, collapse/strip spaces, then repeatedly remove a trailing suffix token sequence among `("c","a")`, `("ca",)`, `("s","a")`, `("sa",)`, `("s","r","l")`, `("srl",)`, `("compania","anonima")`, `("sociedad","anonima")` while more tokens remain; empty result → `company.strip().casefold()`; empty company → `""`.
  - `normalize_tax_id`: uppercase, keep `[0-9A-Z]` only. `is_valid_rif`: `re.fullmatch(r"[VEJPG]\d{8,9}", s)`. `stored_tax_id(raw)`: normalized when valid, else `raw.strip()`.
  - `assign_company_keys(items)`: union-find over item indexes; join items sharing a non-empty `name_key`; join items sharing a valid normalized RIF. Component key: `"n:" + name_key` of its earliest item with non-empty `name_key`; else `"t:" + rif` of its earliest item with a valid RIF; else `"e:" + email` of its earliest item.
  - Tests: `"INVERSIONES EJEMPLO, C.A."`, `"Inversiones Ejemplo C A"` and `"inversiones  ejemplo"` share a key; accents ignored; `"S.R.L."` removed; two different names sharing `J-12345678-9` join; name + RIF chain joins three items; no name and no RIF → `e:` key; no name with valid RIF → `t:` key; order independence of the chosen key.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_companies.py` passes.
- [x] T013 [P] [US1] Implement city normalization in `b2b/cities.py` with tests in `tests/test_cities.py` per plan D8 and contracts/files.md (depends on T008)
  - `match_key`: NFKD, drop combining marks, casefold, `re.sub(r"[^\w\s]", " ", ...)`, collapse/strip spaces.
  - `title_case`: split on spaces; each word `w[:1].upper() + w[1:].lower()`, except `de, del, la, las, los, y` lowercase when not first.
  - `load_city_map(path)`: read with `encoding="utf-8-sig"` and `csv.reader`; header must equal `["variant", "canonical"]` → else `ConfigError(f"{path}: expected header 'variant,canonical'")`; a row without exactly 2 non-empty fields → `ConfigError(f"{path}: line {n}: expected variant,canonical")`; two variants with the same match key and different canonical → `ConfigError(f"{path}: lines {a} and {b}: conflicting canonical names")`.
  - `normalize_city(raw, map)`: empty after strip → `("", False)`; key mapped → `(canonical, False)`; else `(title_case(" ".join(raw.split())), True)`.
  - `aggregate_unmapped_cities(raw_values)`: group non-empty values by `match_key`; one `ReviewItem(type="city_not_in_mapping", ref=SourceRef(), detail=<first value as given>, count=<values in group>)` per key; sorted by `detail.casefold()`.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_cities.py` passes (mapped with accents/case/punctuation, unmapped title-casing with particles, empty, all three config errors, aggregation counts and order).
- [x] T014 [P] [US1] Implement personal/generic classification in `b2b/classify.py` with tests in `tests/test_classify.py` per plan D6 and contracts/files.md (depends on T003, T006)
  - `load_role_words(path)`: UTF-8; strip each line; skip empty and `#` lines; lowercase; a word not matching `^[a-z]+$` → `ConfigError(f"{path}: line {n}: role words must be letters only")`.
  - `reduce_local_part(local)`: `re.sub(r"\d+$", "", local)` then remove `.`, `-`, `_`.
  - `classify(address, words)`: `"generic"` if `reduce_local_part(address.rsplit("@", 1)[0]) in words`, else `"personal"`.
  - Tests: `info@`, `ventas2@`, `atencion.al-cliente@`, `rrhh_01@` generic; `ana.perez@`, `jperez@`, `info.ana@` personal; comment/blank lines; bad line error with number; loading the real `config/role_words.txt` succeeds.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_classify.py` passes.
- [x] T015 [US1] Implement deduplication in `b2b/merge.py` with tests in `tests/test_merge.py` per plan D9 (depends on T007, T012, T013)
  - `completeness(row)`: count of non-empty among `company`, `contact_name`, `city_raw`, `tax_id_raw`, `area`.
  - `group_candidates`: group by `email`; winner = max `completeness`, ties → lowest `order`; `merged` = the rest in `order`; `conflict` = more than one distinct non-empty `name_key(company)` or more than one distinct non-empty `match_key(city_raw)` in the group; return groups sorted by `winner.order`.
  - Tests: three rows same address with completeness 2/4/4 → the earlier 4 wins; conflict on company and on city; no conflict when one side is empty; output order.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_merge.py` passes.
- [x] T016 [US1] Implement contact upsert in `b2b/store.py` with tests in `tests/test_store.py` per plan D10 (depends on T009)
  - Add `ContactValues`, `UpsertResult`, `existing_emails`, `upsert_contacts`, `count_contacts`.
  - `upsert_contacts` (caller holds the transaction): for each value in order — not present → `INSERT` all `ContactValues` fields, `created_at = updated_at = now`, tracking columns omitted (defaults) → `new`; present → compare the 11 descriptive columns (all `ContactValues` fields except `email`); if any differ → `UPDATE contacts SET <those 11 columns>, updated_at = ? WHERE email = ?` → `updated`; else → `unchanged`. No SQL statement in the module may name a tracking column or `created_at` in an `UPDATE`.
  - Tests: insert defaults (times_contacted 0, flags 0, dates NULL); identical re-upsert → unchanged and `updated_at` unchanged; changed city → updated; tracking columns set directly by SQL before an updating upsert are unchanged after it; grep-style test that the module source contains no `UPDATE` mentioning `times_contacted|last_contacted_at|bounced|responded|opted_out|created_at`.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_store.py` passes.
- [x] T017 [P] [US1] Implement report file staging in `b2b/reports.py` with tests in `tests/test_reports.py` per plan D11 and contracts/files.md (depends on T008)
  - `stage_rejects(dir, rows)`: create `dir`; write `dir/.rejects.csv.tmp` with `encoding="utf-8-sig", newline=""`, `csv.writer`, header `source_file,source_sheet,source_row,email_raw,reason`, rows in given order (`source_row` `None` → empty); return the temp path.
  - `stage_review(dir, items)`: same to `dir/.review.csv.tmp`, header `type,source_file,source_sheet,source_row,detail,count`; rows = stable sort of items by `type` (input order kept within a type).
  - `publish(staged, final)`: `os.replace(staged, final)`. `discard(staged)`: remove if it exists.
  - Tests: BOM present, header exact, Spanish accents round-trip, review sort stability, publish replaces an existing file, discard tolerates a missing file.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_reports.py` passes.
- [x] T018 [US1] Implement the import command in `b2b/import_contacts.py` per plan D9–D12, contracts/cli.md and data-model.md (depends on T004, T005, T007, T010–T017)
  - Argparse options, defaults and ranges exactly as contracts/cli.md; invalid values → stderr `import_contacts: error: ...`, return 1. `if __name__ == "__main__": raise SystemExit(main())`.
  - Pipeline: load role words and city map (`ConfigError` → 1); `read_clients`, `read_yearbook` (`InputError` → 1); one `SourceCounts` per source (`rows_read`, `sheets_skipped`). For each row in order: `company_contains_at` → `ReviewItem("company_contains_at", ref, row.company)`; `extract(email_raw)`: no candidates → `RejectedRow(ref, email_raw, invalid[0][1])`, `format_rejected += 1`; else `split_extra += len(candidates) - 1`, ≥ 2 candidates → `multi_address_cell` item (detail `email_raw`), each invalid token when candidates exist → `invalid_token_in_multi_cell` item (detail token). Build `Candidate`s with increasing `order` and `assign_company_keys`. `group_candidates`; `merged` counted on each merged candidate's source, `conflicts` on the winner's source. `check_domains({domain_of(w.email)}, checker or make_dns_checker(timeout), workers)`.
  - Database: `connect`, `ensure_schema` (`SchemaError` → 2); `existing = existing_emails(conn)`. Per group: status `accepts` → `ContactValues` (company, company key, contact name, `normalize_city(...)[0]`, `stored_tax_id`, area, `classify`, winner source columns) queued for upsert; address in `existing` with any other status → not upserted, `existing_unchanged += 1`, `ReviewItem("stored_domain_now_fails", ref, f"{email} ({status})")`; status in `REJECT_STATUSES` → `RejectedRow(ref, winner email_raw, status)`, `domain_rejected += 1`; `unverified` → `ReviewItem("unverified_domain", ref, email)`, `unverified += 1`. Unmapped cities of queued values → `aggregate_unmapped_cities`.
  - Commit sequence: `stage_rejects`, `stage_review`; `with transaction(conn)`: `upsert_contacts(conn, queued, utc_now())`, add `new`/`existing_updated`/`existing_unchanged` per winner source; compute `personal`, `generic`, `missing_city`, `distinct_companies` over stored contacts (queued + existing-with-failing-domain, using this run's computed values); if any `reconciles()` is false → raise to roll back and return 2; after commit `publish` both files. Any exception after staging → `discard` both, return 2 (`sqlite3.Error`) or re-raise; `KeyboardInterrupt` → discard, return 130.
  - Output for this task: stdout `import_contacts: done` then the `database:` and `reports:` lines from contracts/cli.md (full summary comes in T025). Never print contact values.
  - **DoD**: module imports; `.venv/bin/python -m b2b.import_contacts --help` exits 0; T019 passes.
- [x] T019 [US1] Write end-to-end tests for US1 in `tests/test_import_contacts.py` (depends on T018)
  - Using `stub_xls`, `yearbook_xlsx`, `fake_checker`, `db_path` and `--reports-dir`/`--config-dir` pointing at `tmp_path` copies of `config/`: acceptance scenarios US1-1 to US1-10 (stored columns incl. company key and source year; normalization; format rejects in `rejects.csv`; `domain_not_found`/`no_mail_server`/`null_mx` rejects; unverified in `review.csv` and not stored; duplicate winner and merged count via reconciliation; two addresses same company share key; skipped sheets; two-address cell split and reviewed; source files' bytes unchanged).
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_import_contacts.py` passes.

**Checkpoint**: MVP — the database holds only mail-accepting, deduplicated, classified contacts.

---

## Phase 4: User Story 2 — Contact tracking fields (Priority: P1)

**Goal**: tracking fields start clean and survive every re-run; failed runs change nothing.

**Independent Test**: build from synthetic inputs, set tracking fields by SQL, re-run with one
extra address and one domain now failing; tracking values intact, new contact clean, failing
contact unchanged and reviewed, identical contents on a no-change re-run.

- [x] T020 [US2] Add re-run and failure tests to `tests/test_import_contacts.py` for US2 and FR-012 (depends on T019)
  - US2-1 defaults; US2-2 set `times_contacted=2, last_contacted_at, bounced=1, bounced_at, responded=1, responded_at, opted_out=1, opted_out_at` on contacts, re-run with changed city → tracking identical, city updated; US2-3 new row added with defaults; US2-4 fake checker now returns `domain_not_found` for a stored contact → row identical and `stored_domain_now_fails` in `review.csv`; SC-004 two runs with the same inputs → `SELECT * FROM contacts ORDER BY email` identical; FR-012 monkeypatch `store.upsert_contacts` to raise after inserting one row → database identical to before and previous report files unchanged, exit 2.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_import_contacts.py` passes.
- [x] T021 [US2] Report contacts absent from the sources in `b2b/import_contacts.py` (depends on T020)
  - `not_in_sources = len(existing - {g.winner.email for g in groups})`, kept for the summary (T025); add a test in `tests/test_import_contacts.py` where a stored contact's row is removed from the inputs → contact still present, `not_in_sources == 1`.
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_import_contacts.py` passes.

**Checkpoint**: specs 002 and 003 can rely on the tracking fields.

---

## Phase 5: User Story 3 — Personal vs generic classification (Priority: P1)

**Goal**: every stored contact carries the right classification, and edits to the role-word list
take effect on the next run. (The classifier itself, T014, is in Phase 3 because
`classification` is a required column.)

**Independent Test**: synthetic role and personal addresses produce the right labels and
per-source counts; adding a word to a temporary `role_words.txt` reclassifies an existing contact
on re-run without touching its tracking fields.

- [x] T022 [US3] Add classification end-to-end tests to `tests/test_import_contacts.py` (depends on T021)
  - US3-1/US3-2 `classification` stored per address (role-word and personal examples); a role word added to the temporary `role_words.txt` reclassifies an existing contact on re-run → its `classification` and `updated_at` change, tracking columns unchanged. (US3-3 per-source counts are asserted from the summary in T025.)
  - **DoD**: `.venv/bin/python -m pytest -q tests/test_import_contacts.py` passes.

---

## Phase 6: User Story 4 — Quality report before any use of the database (Priority: P2)

**Goal**: the operator reads a counts-only summary that reconciles, plus complete review items.

**Independent Test**: synthetic inputs with every defect type → summary numbers reconcile per
source, every anomaly listed, and no synthetic address, company, contact or city value appears
on stdout or stderr.

- [x] T023 [P] [US4] Implement `format_summary` in `b2b/reports.py` with tests in `tests/test_reports.py` per contracts/cli.md (depends on T017)
  - Lines: `import_contacts: done`; per source `source: {file} (year {year})` and for total `total`; then for each block, in contract order, `"  " + f"{label + ':':<24}{value:>7}"` using labels `rows read`, `extra from split cells`, `rejected (format)`, `merged duplicates`, `duplicate conflicts`, `new contacts`, `existing updated`, `existing unchanged`, `rejected (domain)`, `unverified`, `personal`, `generic`, `missing city`, `distinct companies`, preceded by `"  " + f"{'sheets skipped:':<24}" + (", ".join(names) or "-")`; after the total block `"  " + f"{'contacts not in sources:':<24}{n:>7}"`; then `database: {db_path} ({contacts} contacts)` and `reports:  {rejects_path} ({rejects_rows} rows), {review_path} ({review_rows} rows)`. Joined with `\n`, trailing newline.
  - **DoD**: golden-string test for a two-source summary passes; `.venv/bin/python -m pytest -q tests/test_reports.py` passes.
- [x] T024 [US4] Print the full summary and route all errors to stderr in `b2b/import_contacts.py` (depends on T021, T023)
  - After publish: `print(format_summary(per_source, total_counts(per_source, <distinct company keys over all stored contacts>), not_in_sources, db_path, count_contacts(conn), rejects_path, len(rejected), review_path, len(review_items)), end="")`. Every error path prints exactly one `import_contacts: error: ...` line to stderr per contracts/cli.md.
  - **DoD**: module runs; T025 passes.
- [x] T025 [US4] Add summary and error-output tests to `tests/test_import_contacts.py` (depends on T024)
  - US4-1 every block reconciles and totals equal the sums (distinct companies from the union); US3-3 `personal` and `generic` lines match the expected per-source counts; US4-2 every review type present for a crafted input; US4-3 `capsys` stdout+stderr contain none of the fixture addresses, companies, contact names or cities; missing header → exit 1, no database file, no report files; bad `cities.csv` header → exit 1; `--dns-workers 0` → exit 1.
  - **DoD**: `.venv/bin/python -m pytest -q` (full suite) passes.

**Checkpoint**: feature complete on synthetic data.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T026 Run the full suite `.venv/bin/python -m pytest -q` and fix failures through the loop (re-delegate or Claude per the classification below)
  - **DoD**: all tests pass; no test touches the network, `contactos/`, `.env` or `data/`.
- [x] T027 Run the real import per `specs/001-clean-contact-list/quickstart.md` §2–§3 (needs explicit user authorization for this run)
  - `.venv/bin/python -m b2b.import_contacts`, then the §3 count-only checks.
  - **DoD**: exit 0; rows read 1,620 and 1,287; sheets `SQL` and `14-100` skipped; schema version 1; zero duplicate emails; tracking non-default 0; counts (no values) recorded in `docs/CHANGELOG.md`.
- [x] T028 Verify re-run safety per quickstart §4 using a copy `data/b2b-rerun-check.sqlite3`, then delete the copy
  - **DoD**: second real run reports `new contacts: 0`, `existing updated: 0`; tracking values set on the copy unchanged after running with `--db` on the copy; copy removed.
- [ ] T029 [P] Operator checks: SC-003 classification sample of 50 (quickstart §5) and report review (quickstart §6); update `config/role_words.txt` / `config/cities.csv` and re-run if needed
  - **DoD**: operator confirms ≥ 48 of 50 correct; any config edits re-run cleanly.
- [x] T030 [P] Update docs: `docs/CHANGELOG.md` (feature entry with files added) and the Stack section of `.claude/CLAUDE.md` (replace "there is no code yet" with the `b2b/` package and the `import_contacts` command)
  - **DoD**: both files updated; no contact values in either.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 → T002; T003–T005 in parallel with T001.
- **Foundational (Phase 2)**: needs T002 (and T003). T006 first; then T007, T008, T009 (T008 and T009 in parallel; T007 after T003+T006).
- **US1 (Phase 3)**: needs Phase 2. T010, T011, T012, T014, T017 in parallel; T013 after T008; T015 after T007+T012+T013; T016 after T009; T018 after all of them plus T004–T005; T019 after T018.
- **US2 (Phase 4)**: after T019 (tests build on the US1 pipeline).
- **US3 (Phase 5)**: after T021.
- **US4 (Phase 6)**: T023 can start any time after T017; T024 after T021+T023; T025 after T024.
- **Polish (Phase 7)**: after T025; T027 and T028 need user authorization for real runs.

### Story Dependencies

```text
Setup ─► Foundational ─► US1 (MVP) ─► US2 ─► US3 ─► US4 ─► Polish
                                   └──────── T023 (US4 formatter) can run alongside US1–US3
```

US2–US4 are test-and-output increments on the single import pipeline, so they follow US1
rather than running independently.

### Within Each Task

- Module and its tests are delivered together; the task is complete only when its test file
  passes and the audit checklist in `.claude/CLAUDE.md` is clean.
- Mark `[x]` here when complete.

---

## Parallel Examples

```text
# Phase 1
T003 b2b/__init__.py   |  T004 config/role_words.txt  |  T005 config/cities.csv

# Phase 2 (after T006)
T008 b2b/reports.py entities  |  T009 b2b/store.py schema   (T007 sources once T003 is done)

# Phase 3 (after Phase 2) — independent modules
T010 emails.py  |  T011 domains.py  |  T012 companies.py  |  T014 classify.py  |  T017 report staging
# then
T013 cities.py (needs T008)  →  T015 merge.py  |  T016 store upsert  →  T018 import_contacts.py  →  T019 tests

# Phase 6
T023 format_summary can be delegated while Phases 4–5 are in progress
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 + Phase 2.
2. Phase 3 (T010–T019).
3. **Stop and validate**: full suite passes on synthetic data. The real import (T027) waits for
   explicit authorization.

### Incremental Delivery

1. US1 → database of valid contacts.
2. US2 → re-run and failure safety proven (prerequisite for specs 002 and 003).
3. US3 → classification refresh proven.
4. US4 → full counts-only summary and error contract.
5. Polish → real import, re-run check, operator review, docs.

---

## Delegation Classification

Per `.claude/CLAUDE.md`. DEEPSEEK tasks are sent one per `deepseek-executor` call with this
file's Shared interface block and the cited plan decisions quoted verbatim.

| Task | Executor | Reason |
|------|----------|--------|
| T001 | CLAUDE | dependency pins (setup) |
| T002 | CLAUDE | package install, needs authorization |
| T003 | DEEPSEEK | two exception classes, fully pinned |
| T004 | DEEPSEEK | literal list from D6 |
| T005 | DEEPSEEK | literal list in task |
| T006 | CLAUDE | network guard for all tests |
| T007 | DEEPSEEK | spreadsheet column mapping and normalization, pinned (D3) |
| T008 | DEEPSEEK | dataclasses and arithmetic, pinned |
| T009 | CLAUDE | schema and transaction safety guard the tracker |
| T010 | DEEPSEEK | normalization helper, pinned (D4) |
| T011 | CLAUDE | network behavior and failure classification decide who is stored |
| T012 | DEEPSEEK | pure normalization/grouping, pinned (D7) |
| T013 | DEEPSEEK | city normalization, pinned (D8) |
| T014 | DEEPSEEK | classification rule, pinned (D6) |
| T015 | CLAUDE | decides which record represents a contact (contact data rules) |
| T016 | CLAUDE | upsert must never touch tracking fields (send-path safety) |
| T017 | DEEPSEEK | CSV writing, pinned (D11) |
| T018 | CLAUDE | orchestration, transaction, reconciliation, exit codes |
| T019 | CLAUDE | end-to-end safety tests across modules |
| T020 | CLAUDE | tracking preservation and rollback tests |
| T021 | CLAUDE | pipeline change |
| T022 | CLAUDE | end-to-end tests |
| T023 | DEEPSEEK | summary formatting, pinned (contracts/cli.md) |
| T024 | CLAUDE | pipeline output and error routing |
| T025 | CLAUDE | no-contact-values guarantee tests |
| T026–T028 | CLAUDE | test runs and real-data runs |
| T029 | OPERATOR | manual review of real contacts |
| T030 | CLAUDE | project docs |

**Totals**: 11 DEEPSEEK, 18 CLAUDE, 1 OPERATOR.

## Notes

- `[P]` tasks touch different files and have no incomplete dependencies.
- No git: list every changed file in each task report and add the change to `docs/CHANGELOG.md`.
- Never run anything against `contactos/` or `data/` outside T027–T029.
