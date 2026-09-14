"""Tests for the manual inbox-check command that releases the batch hold."""
import sqlite3
from datetime import datetime, timezone

from b2b import store, tracking
from b2b.mark_inbox_checked import main


def test_records_inbox_run_and_releases_hold(db_path, capsys):
    conn = store.connect(db_path)
    store.ensure_schema(conn)
    conn.execute("INSERT INTO runs (kind, campaign, step, started_at, finished_at) "
                 "VALUES ('send_production', 'c', 1, '2026-09-14T13:00:00Z', '2026-09-14T18:00:00Z')")
    assert not tracking.batch_hold_satisfied(conn)
    conn.close()

    assert main(["--db", str(db_path)], now=lambda: datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)) == 0
    assert capsys.readouterr().out == "mark_inbox_checked: recorded manual inbox check at 2026-09-15T12:00:00Z\n"

    conn = store.connect(db_path)
    assert tracking.batch_hold_satisfied(conn)
    rows = conn.execute("SELECT kind, started_at, finished_at, stop_reason FROM runs WHERE kind = 'inbox'").fetchall()
    assert [tuple(r) for r in rows] == [("inbox", "2026-09-15T12:00:00Z", "2026-09-15T12:00:00Z", "manual_check")]


def test_missing_database_exits_2(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "missing.sqlite3")]) == 2
    assert "database not found" in capsys.readouterr().err
    assert not (tmp_path / "missing.sqlite3").exists()


def test_newer_schema_exits_2(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 9")
    conn.close()
    assert main(["--db", str(db_path)]) == 2
