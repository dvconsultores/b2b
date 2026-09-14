import sqlite3
from pathlib import Path

import pytest

from b2b import store
from b2b.store import ContactValues

TRACKING_COLUMNS = {
    "times_contacted",
    "last_contacted_at",
    "bounced",
    "bounced_at",
    "responded",
    "responded_at",
    "opted_out",
    "opted_out_at",
}

EXPECTED_COLUMNS = [
    "id", "email", "company", "company_key", "contact_name", "city", "tax_id", "area",
    "classification", "source_file", "source_sheet", "source_row", "source_year",
    "times_contacted", "last_contacted_at", "bounced", "bounced_at", "responded",
    "responded_at", "opted_out", "opted_out_at", "created_at", "updated_at",
    "verification", "verified_at",
]

RUN_COLUMNS = ["id", "kind", "campaign", "step", "started_at", "finished_at", "stop_reason", "forced_no_dmarc"]

ATTEMPT_COLUMNS = [
    "id", "run_id", "contact_id", "campaign", "step", "status", "error_kind", "smtp_code",
    "message_id", "created_at", "finished_at",
]


def _open(db_path):
    conn = store.connect(db_path)
    store.ensure_schema(conn)
    return conn


def _values(email="ana@example.com", **overrides):
    base = dict(
        email=email,
        company="Ejemplo Uno, C.A.",
        company_key="n:ejemplo uno",
        contact_name="",
        city="Caracas",
        tax_id="J123456789",
        area="",
        classification="personal",
        source_file="ClientesFebrero2020.xls",
        source_sheet="Clientes",
        source_row=2,
        source_year=2020,
    )
    base.update(overrides)
    return ContactValues(**base)


def _insert_minimal(conn, **columns):
    row = dict(
        email="x@example.com", company_key="n:x", classification="personal",
        source_file="f", source_sheet="s", source_row=2, source_year=2020,
        created_at="2026-09-13T00:00:00Z", updated_at="2026-09-13T00:00:00Z",
    )
    row.update(columns)
    names = ", ".join(row)
    conn.execute(f"INSERT INTO contacts ({names}) VALUES ({', '.join('?' for _ in row)})",
                 tuple(row.values()))


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _insert_run(conn, **columns):
    row = dict(kind="send_production", campaign="c", step=1, started_at="2026-09-14T13:00:00Z")
    row.update(columns)
    cur = conn.execute(f"INSERT INTO runs ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                       tuple(row.values()))
    return cur.lastrowid


def _insert_attempt(conn, run_id, contact_id, **columns):
    row = dict(run_id=run_id, contact_id=contact_id, campaign="c", step=1, status="pending",
               created_at="2026-09-14T13:00:00Z")
    row.update(columns)
    conn.execute(f"INSERT INTO send_attempts ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                 tuple(row.values()))


def test_connect_creates_parent_directory(db_path):
    store.connect(db_path).close()
    assert db_path.parent.is_dir()


def test_fresh_database_gets_schema_v3(db_path):
    conn = _open(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert _columns(conn, "contacts") == EXPECTED_COLUMNS
    assert _columns(conn, "runs") == RUN_COLUMNS
    assert _columns(conn, "send_attempts") == ATTEMPT_COLUMNS
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_contacts_company_key", "idx_runs_kind_started", "idx_attempts_created",
            "idx_attempts_campaign"} <= indexes


def test_ensure_schema_is_idempotent(db_path):
    conn = _open(db_path)
    store.ensure_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3


def test_v2_database_migrates_to_unverified(db_path):
    conn = store.connect(db_path)
    conn.execute(store._CREATE_CONTACTS)
    conn.execute(store._CREATE_COMPANY_KEY_INDEX)
    conn.execute("PRAGMA user_version = 1")
    store._migrate_1_to_2(conn)
    _insert_minimal(conn, bounced=1, bounced_at="2026-09-02T00:00:00Z")
    before = tuple(conn.execute("SELECT * FROM contacts").fetchone())
    store.ensure_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert tuple(conn.execute("SELECT * FROM contacts").fetchone()) == (*before, "unverified", None)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE contacts SET verification = 'maybe'")


def test_v1_database_migrates_keeping_contacts(db_path):
    conn = store.connect(db_path)
    conn.execute(store._CREATE_CONTACTS)
    conn.execute(store._CREATE_COMPANY_KEY_INDEX)
    conn.execute("PRAGMA user_version = 1")
    _insert_minimal(conn, times_contacted=2, last_contacted_at="2026-09-01T00:00:00Z",
                    bounced=1, bounced_at="2026-09-02T00:00:00Z")
    before = tuple(conn.execute("SELECT * FROM contacts").fetchone())
    store.ensure_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert tuple(conn.execute("SELECT * FROM contacts").fetchone())[: len(before)] == before
    assert _columns(conn, "send_attempts") == ATTEMPT_COLUMNS


def test_newer_schema_version_is_refused(db_path):
    conn = store.connect(db_path)
    conn.execute("PRAGMA user_version = 4")
    with pytest.raises(store.SchemaError, match="schema version 4 is newer than this tool"):
        store.ensure_schema(conn)


def test_unversioned_contacts_table_is_refused(db_path):
    conn = store.connect(db_path)
    conn.execute("CREATE TABLE contacts (id INTEGER)")
    with pytest.raises(store.SchemaError):
        store.ensure_schema(conn)


@pytest.mark.parametrize(
    "columns",
    [
        {"bounced": 1},
        {"responded": 1},
        {"opted_out": 1},
        {"times_contacted": 1},
        {"last_contacted_at": "2026-09-13T00:00:00Z"},
        {"classification": "unknown"},
        {"source_year": 2021},
    ],
)
def test_checks_reject_inconsistent_rows(db_path, columns):
    conn = _open(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_minimal(conn, **columns)


def test_duplicate_attempt_for_contact_campaign_step_rejected(db_path):
    conn = _open(db_path)
    _insert_minimal(conn)
    run_id = _insert_run(conn)
    _insert_attempt(conn, run_id, 1)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_attempt(conn, run_id, 1, status="unknown", finished_at="2026-09-14T13:01:00Z")


@pytest.mark.parametrize(
    "columns",
    [
        {"status": "pending", "finished_at": "2026-09-14T13:01:00Z"},
        {"status": "unknown"},
        {"status": "accepted", "finished_at": "2026-09-14T13:01:00Z"},
        {"status": "temporary_failure", "finished_at": "2026-09-14T13:01:00Z", "message_id": "<x@example.com>"},
        {"status": "sent", "finished_at": "2026-09-14T13:01:00Z"},
        {"step": 2},
    ],
)
def test_attempt_checks_reject_inconsistent_rows(db_path, columns):
    conn = _open(db_path)
    _insert_minimal(conn)
    run_id = _insert_run(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_attempt(conn, run_id, 1, **columns)


def test_attempt_requires_existing_contact_and_run(db_path):
    conn = _open(db_path)
    _insert_minimal(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_attempt(conn, 999, 1)


def test_run_kind_checked(db_path):
    conn = _open(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_run(conn, kind="other")


def test_transaction_rolls_back_on_error(db_path):
    conn = _open(db_path)
    with pytest.raises(RuntimeError):
        with store.transaction(conn):
            _insert_minimal(conn)
            raise RuntimeError("boom")
    assert store.count_contacts(conn) == 0


def test_utc_now_format():
    value = store.utc_now()
    assert len(value) == 20 and value.endswith("Z") and value[10] == "T"


def test_insert_uses_tracking_defaults(db_path):
    conn = _open(db_path)
    with store.transaction(conn):
        result = store.upsert_contacts(conn, [_values()], "2026-09-13T10:00:00Z")
    assert result.new == ["ana@example.com"] and not result.updated and not result.unchanged
    row = conn.execute("SELECT * FROM contacts").fetchone()
    assert row["times_contacted"] == 0 and row["last_contacted_at"] is None
    assert (row["bounced"], row["responded"], row["opted_out"]) == (0, 0, 0)
    assert row["bounced_at"] is None and row["responded_at"] is None and row["opted_out_at"] is None
    assert row["created_at"] == row["updated_at"] == "2026-09-13T10:00:00Z"
    assert store.existing_emails(conn) == {"ana@example.com"}
    assert store.count_contacts(conn) == 1


def test_identical_upsert_is_unchanged(db_path):
    conn = _open(db_path)
    with store.transaction(conn):
        store.upsert_contacts(conn, [_values()], "2026-09-13T10:00:00Z")
    with store.transaction(conn):
        result = store.upsert_contacts(conn, [_values()], "2026-09-14T10:00:00Z")
    assert result.unchanged == ["ana@example.com"]
    assert conn.execute("SELECT updated_at FROM contacts").fetchone()[0] == "2026-09-13T10:00:00Z"


def test_changed_descriptive_value_updates(db_path):
    conn = _open(db_path)
    with store.transaction(conn):
        store.upsert_contacts(conn, [_values()], "2026-09-13T10:00:00Z")
    with store.transaction(conn):
        result = store.upsert_contacts(conn, [_values(city="Valencia")], "2026-09-14T10:00:00Z")
    assert result.updated == ["ana@example.com"]
    row = conn.execute("SELECT city, created_at, updated_at FROM contacts").fetchone()
    assert tuple(row) == ("Valencia", "2026-09-13T10:00:00Z", "2026-09-14T10:00:00Z")


def test_update_never_changes_tracking_columns(db_path):
    conn = _open(db_path)
    with store.transaction(conn):
        store.upsert_contacts(conn, [_values()], "2026-09-13T10:00:00Z")
    conn.execute(
        "UPDATE contacts SET times_contacted = 2, last_contacted_at = 'a', bounced = 1, "
        "bounced_at = 'b', responded = 1, responded_at = 'c', opted_out = 1, opted_out_at = 'd'"
    )
    tracked = "SELECT " + ", ".join(sorted(TRACKING_COLUMNS)) + ", created_at FROM contacts"
    before = tuple(conn.execute(tracked).fetchone())
    with store.transaction(conn):
        result = store.upsert_contacts(
            conn, [_values(company="Otro", classification="generic")], "2026-09-15T10:00:00Z"
        )
    assert result.updated == ["ana@example.com"]
    assert tuple(conn.execute(tracked).fetchone()) == before


def test_descriptive_columns_exclude_tracking_and_created_at():
    assert not (set(store.DESCRIPTIVE_COLUMNS) & (TRACKING_COLUMNS | {"created_at", "email", "id"}))
    assert len(store.DESCRIPTIVE_COLUMNS) == 11


def test_module_has_no_update_touching_tracking_columns():
    source = Path(store.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        if "UPDATE" in line:
            assert not any(column in line for column in TRACKING_COLUMNS | {"created_at"}), line
