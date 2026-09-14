"""Spec 004: verification export, results parsing and import (synthetic data only)."""
import sqlite3
import stat
from datetime import datetime, timezone

import pytest

from b2b import InputError, store
from b2b.export_verification import main as export_main
from b2b.import_verification import main as import_main
from b2b.verification import apply_results, read_results

NOW = "2026-09-15T12:00:00Z"


def verification_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT email, verification FROM contacts"))
    finally:
        conn.close()


def write_csv(tmp_path, text, name="results.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def unverified(contacts_db):
    return contacts_db([
        {"email": "ana@example.com", "company_key": "n:a", "verification": "unverified"},
        {"email": "luis@example.org", "company_key": "n:b", "verification": "unverified"},
        {"email": "eva@example.net", "company_key": "n:c", "verification": "unverified"},
        {"email": "old@example.com", "company_key": "n:d", "verification": "unverified",
         "opted_out": 1, "opted_out_at": "2026-09-14T00:00:00Z"},
    ])


# --- read_results ---------------------------------------------------------------------------------


def test_neverbounce_style_results(tmp_path):
    path = write_csv(tmp_path, "email,result\nAna@Example.com ,valid\nluis@example.org,catchall\n"
                               "eva@example.net,disposable\nx@example.com,unknown\n,valid\n\n")
    parsed = read_results(path)
    assert parsed.results == {"ana@example.com": "valid", "luis@example.org": "catch_all",
                              "eva@example.net": "invalid", "x@example.com": "unknown"}
    assert (parsed.rows, parsed.blank_email, parsed.unrecognized_status) == (5, 1, 0)


def test_zerobounce_style_results_with_bom_and_semicolons(tmp_path):
    path = tmp_path / "zb.csv"
    path.write_text("﻿Email;ZB Status;ZB Sub Status\nana@example.com;catch-all;\nluis@example.org;do_not_mail;role_based\n",
                    encoding="utf-8")
    assert read_results(path).results == {"ana@example.com": "catch_all", "luis@example.org": "invalid"}


def test_column_overrides_and_unrecognized(tmp_path):
    path = write_csv(tmp_path, "correo,estado\nana@example.com,valid\nluis@example.org,quizas\n")
    with pytest.raises(InputError, match="no email column found"):
        read_results(path)
    parsed = read_results(path, email_column="Correo", status_column="estado")
    assert parsed.results == {"ana@example.com": "valid"} and parsed.unrecognized_status == 1
    with pytest.raises(InputError, match="status column 'nope' not found; columns: correo, estado"):
        read_results(path, email_column="correo", status_column="nope")


def test_unreadable_or_empty(tmp_path):
    with pytest.raises(InputError, match="cannot read file"):
        read_results(tmp_path / "missing.csv")
    with pytest.raises(InputError, match="empty file"):
        read_results(write_csv(tmp_path, ""))


# --- apply_results --------------------------------------------------------------------------------


def test_apply_results(unverified, db_path):
    conn = store.connect(db_path)
    applied = apply_results(conn, {"ana@example.com": "valid", "luis@example.org": "invalid",
                                   "nobody@example.com": "valid"}, NOW)
    assert (applied.matched, applied.not_in_database) == (2, 1)
    assert applied.by_status == {"valid": 1, "catch_all": 0, "unknown": 0, "invalid": 1}
    rows = verification_rows(db_path)
    assert (rows["ana@example.com"], rows["luis@example.org"], rows["eva@example.net"]) == ("valid", "invalid", "unverified")
    assert conn.execute("SELECT verified_at FROM contacts WHERE email = 'ana@example.com'").fetchone()[0] == NOW


def test_apply_results_dry_run(unverified, db_path):
    before = verification_rows(db_path)
    apply_results(store.connect(db_path), {"ana@example.com": "valid"}, NOW, dry_run=True)
    assert verification_rows(db_path) == before


# --- export command -------------------------------------------------------------------------------


def test_export_writes_emails_only_with_private_permissions(unverified, db_path, tmp_path, capsys):
    out_dir = tmp_path / "verification"
    clock = lambda: datetime(2026, 9, 15, 12, 30, 5, tzinfo=timezone.utc)  # noqa: E731
    assert export_main(["--db", str(db_path), "--out-dir", str(out_dir)], now=clock) == 0
    path = out_dir / "verify-emails-20260915-123005.csv"
    assert path.read_text(encoding="utf-8") == "email\nana@example.com\nluis@example.org\neva@example.net\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(out_dir.stat().st_mode) == 0o700
    assert capsys.readouterr().out == f"export_verification: exported 3 addresses to {path} (already verified: 0)\n"

    assert export_main(["--db", str(db_path), "--out-dir", str(out_dir)], now=clock) == 1
    assert "already exists" in capsys.readouterr().err


def test_export_nothing_left(contacts_db, db_path, tmp_path, capsys):
    contacts_db([{"email": "ana@example.com"}])  # fixture default: already valid
    assert export_main(["--db", str(db_path), "--out-dir", str(tmp_path / "v")]) == 0
    assert capsys.readouterr().out == "export_verification: nothing to export (already verified: 1)\n"
    assert not (tmp_path / "v").exists()


def test_export_missing_database(tmp_path):
    assert export_main(["--db", str(tmp_path / "none.sqlite3"), "--out-dir", str(tmp_path)]) == 2


# --- import command -------------------------------------------------------------------------------


def test_import_command_counts_only(unverified, db_path, tmp_path, capsys):
    path = write_csv(tmp_path, "email,result\nana@example.com,valid\nluis@example.org,invalid\nzz@example.com,valid\n")
    assert import_main([str(path), "--db", str(db_path), "--dry-run"], now=NOW) == 0
    assert verification_rows(db_path)["ana@example.com"] == "unverified"
    capsys.readouterr()
    assert import_main([str(path), "--db", str(db_path)], now=NOW) == 0
    out = capsys.readouterr().out
    assert out == ("import_verification: rows 3 | blank email 0 | matched 2 | not in database 1 | "
                   "valid 1 | catch_all 0 | unknown 0 | invalid 1\n")
    assert verification_rows(db_path)["luis@example.org"] == "invalid"


def test_import_refuses_unrecognized_statuses(unverified, db_path, tmp_path, capsys):
    path = write_csv(tmp_path, "email,status\nana@example.com,valid\nluis@example.org,Luis Pérez\n")
    before = verification_rows(db_path)
    assert import_main([str(path), "--db", str(db_path)]) == 1
    err = capsys.readouterr().err
    assert "1 rows have an unrecognized status; nothing imported" in err
    assert "Luis" not in err and "@" not in err
    assert verification_rows(db_path) == before


def test_import_errors(unverified, db_path, tmp_path, capsys):
    assert import_main([str(tmp_path / "missing.csv"), "--db", str(db_path)]) == 1
    assert import_main([str(write_csv(tmp_path, "email,result\n")), "--db", str(tmp_path / "none.sqlite3")]) == 2
