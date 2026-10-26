"""Spec 006 plan D4: the Artemisa tracker database."""
import sqlite3
from datetime import datetime, timezone

import pytest

from b2b import artemisa_store, store, tracking
from b2b.artemisa_csv import ArtemisaRow
from b2b.mailer import SendOutcome

NOW = "2026-10-25T12:00:00Z"


def row(user_id, email, first_name="ANA", nickname="", types="SELL"):
    return ArtemisaRow(user_id, email, first_name, nickname, types)


def open_db(path):
    conn = artemisa_store.connect(path)
    artemisa_store.ensure_schema(conn)
    return conn


def test_schema_created_with_spec_002_tracking_tables(db_path):
    conn = open_db(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"contacts", "runs", "send_attempts"} <= tables
    columns = [r[1] for r in conn.execute("PRAGMA table_info(contacts)")]
    assert "user_id" in columns and "company" not in columns and "phone" not in columns
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    artemisa_store.ensure_schema(conn)  # idempotent
    conn.close()


def test_refuses_the_b2b_database(db_path):
    conn = store.connect(db_path)
    store.ensure_schema(conn)
    with pytest.raises(store.SchemaError, match="not an Artemisa database"):
        artemisa_store.ensure_schema(conn)
    conn.close()


def test_refuses_newer_schema(db_path):
    conn = open_db(db_path)
    conn.execute("PRAGMA user_version = 9")
    with pytest.raises(store.SchemaError, match="newer than this tool"):
        artemisa_store.ensure_schema(conn)
    conn.close()


def test_upsert_keyed_by_user_id_and_conflicts(db_path):
    conn = open_db(db_path)
    with store.transaction(conn):
        result = artemisa_store.upsert_contacts(conn, [row(1, "ana@example.com"), row(2, "luis@example.org")], NOW)
    assert (result.new, result.updated, result.unchanged, result.conflict) == (2, 0, 0, 0)
    conn.execute("UPDATE contacts SET times_contacted = 1, last_contacted_at = ? WHERE user_id = 1", (NOW,))
    with store.transaction(conn):
        result = artemisa_store.upsert_contacts(conn, [
            row(1, "ana@example.com", nickname="anita"),   # updated
            row(2, "luis@example.org"),                     # unchanged
            row(3, "ana@example.com"),                      # conflict: email belongs to user 1
            row(4, "sara@example.net"),                     # new
        ], "2026-10-26T12:00:00Z")
    assert (result.new, result.updated, result.unchanged, result.conflict) == (1, 1, 1, 1)
    ana = conn.execute("SELECT nickname, times_contacted, created_at, updated_at FROM contacts WHERE user_id = 1").fetchone()
    assert tuple(ana) == ("anita", 1, NOW, "2026-10-26T12:00:00Z")
    assert artemisa_store.count_contacts(conn) == 3
    conn.close()


def test_select_recipients_excludes_attempted_bounced_opted_out(db_path):
    conn = open_db(db_path)
    with store.transaction(conn):
        artemisa_store.upsert_contacts(conn, [row(i, f"u{i}@example.com", first_name=f"N{i}") for i in range(1, 6)], NOW)
    run_id = tracking.start_run(conn, "camp", 1, False, NOW)
    attempt = tracking.record_pending(conn, run_id, 1, "camp", 1, NOW)
    tracking.record_outcome(conn, attempt, 1, SendOutcome("accepted", None, 250, "<m@example.com>", False), NOW)
    attempt = tracking.record_pending(conn, run_id, 2, "camp", 1, NOW)
    tracking.record_outcome(conn, attempt, 2, SendOutcome("temporary_failure", "data_deferred", 451, None, False), NOW)
    conn.execute("UPDATE contacts SET bounced = 1, bounced_at = ? WHERE id = 3", (NOW,))
    conn.execute("UPDATE contacts SET opted_out = 1, opted_out_at = ? WHERE id = 4", (NOW,))
    attempt = tracking.record_pending(conn, run_id, 5, "other", 1, NOW)
    tracking.record_outcome(conn, attempt, 5, SendOutcome("accepted", None, 250, "<n@example.com>", False), NOW)
    chosen = artemisa_store.select_recipients(conn, "camp")
    assert [(r.contact_id, r.email, r.first_name) for r in chosen] == [(5, "u5@example.com", "N5")]
    assert conn.execute("SELECT times_contacted FROM contacts WHERE id = 1").fetchone()[0] == 1
    conn.close()


def test_attempts_in_last_day(db_path):
    conn = open_db(db_path)
    with store.transaction(conn):
        artemisa_store.upsert_contacts(conn, [row(1, "a@example.com"), row(2, "b@example.com")], NOW)
    run_id = tracking.start_run(conn, "camp", 1, False, NOW)
    tracking.record_pending(conn, run_id, 1, "camp", 1, "2026-10-24T11:00:00Z")
    tracking.record_pending(conn, run_id, 2, "camp", 1, "2026-10-25T11:00:00Z")
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    assert artemisa_store.attempts_in_last_day(conn, now) == (1, "2026-10-25T11:00:00Z")
    conn.close()
