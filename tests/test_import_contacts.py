"""End-to-end tests for the import command on synthetic spreadsheets (spec 001 US1–US4)."""
from __future__ import annotations

import csv
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from b2b import import_contacts, store

ROOT = Path(__file__).resolve().parents[1]

CLIENT_HEADER = ["RIF", "NOMBRE", "DIR1", "DIR2", "DIR3", "TLF", "CIUDAD", "MAIL", "AREA"]
YEARBOOK_HEADER = ["EMPRESA", "CONTACTO", "CORREO", "CIUDAD"]


def client(rif, name, city, mail, area=""):
    return [rif, name, "", "", "", "", city, mail, area]


def base_clients():
    return {
        "Clientes": [
            CLIENT_HEADER,
            client("J-12345678-9", "INVERSIONES UNO, C.A.", "caracas", "  Ana.Perez@Example.COM ", "Comercio"),  # 2
            client("J-12345678-9", "Inversiones Uno", "Caracas", "ventas@example.com"),  # 3 generic
            client("J-22222222-2", "Comercial Dos", "", ""),  # 4 empty email
            client("J-33333333-3", "Comercial Tres", "Valencia", "no-es-correo"),  # 5 invalid
            client("J-44444444-4", "Comercial Cuatro", "Maracay", "luis@example.com"),  # 6 merged
            client("J-44444444-4", "Comercial Cuatro", "Maracay", "luis@example.com", "Industria"),  # 7 winner
            client("J-55555555-5", "Muerta Andina", "Coro", "pedro@dead.example"),  # 8 domain_not_found
            client("J-66666666-6", "Sin Servidor", "Coro", "rosa@nomx.example"),  # 9 no_mail_server
            client("J-77777777-7", "Nulo Norte", "Coro", "juan@nullmx.example"),  # 10 null_mx
            client("J-88888888-8", "Lenta Sur", "Coro", "eva@slow.example"),  # 11 unverified
            client("J-99999999-9", "Pueblo Raro", "Villa Inventada", "marta@example.org"),  # 12 unmapped city
        ],
        "SQL": [],
    }


def base_yearbook():
    return {
        "1-100": [
            YEARBOOK_HEADER,
            ["Grupo Cinco", "Carla Gomez", "carla@example.net; carlos@example.net", "Mérida"],  # 2 split
            ["correo@example.net", "Mario Rivas", "mario@example.net", "Barinas"],  # 3 company has @
            ["Grupo Seis", "Sofia Leal", "sofia@example.com / mal@", ""],  # 4 invalid token, no city
        ],
        "14-100": [YEARBOOK_HEADER],
    }


STATUSES = {
    "dead.example": "domain_not_found",
    "nomx.example": "no_mail_server",
    "nullmx.example": "null_mx",
    "slow.example": "unverified",
}

STORED = {
    "ana.perez@example.com",
    "ventas@example.com",
    "luis@example.com",
    "marta@example.org",
    "carla@example.net",
    "carlos@example.net",
    "mario@example.net",
    "sofia@example.com",
}

CONTACT_VALUES = [
    "Ana.Perez@Example.COM", "ana.perez@example.com", "ventas@example.com", "no-es-correo",
    "luis@example.com", "pedro@dead.example", "rosa@nomx.example", "juan@nullmx.example",
    "eva@slow.example", "marta@example.org", "carla@example.net", "carlos@example.net",
    "mario@example.net", "sofia@example.com", "mal@", "INVERSIONES UNO", "Inversiones Uno",
    "Comercial Dos", "Comercial Tres", "Comercial Cuatro", "Muerta Andina", "Sin Servidor",
    "Nulo Norte", "Lenta Sur", "Pueblo Raro", "Grupo Cinco", "Grupo Seis", "Carla Gomez",
    "Mario Rivas", "Sofia Leal", "Villa Inventada", "Caracas", "caracas", "Maracay", "Valencia",
    "Mérida", "Barinas", "Coro", "J-12345678-9", "J123456789", "Comercio", "Industria",
]


@pytest.fixture
def config_dir(tmp_path):
    target = tmp_path / "config"
    shutil.copytree(ROOT / "config", target)
    return target


@pytest.fixture
def run_import(tmp_path, stub_xls, yearbook_xlsx, fake_checker, db_path, config_dir):
    reports_dir = tmp_path / "data" / "reports"

    def run(clients=None, yearbook=None, statuses=None, extra=()):
        clients_path = stub_xls(base_clients() if clients is None else clients)
        yearbook_path = yearbook_xlsx(base_yearbook() if yearbook is None else yearbook)
        run.yearbook_path = yearbook_path
        argv = [
            "--clients", str(clients_path),
            "--yearbook", str(yearbook_path),
            "--db", str(db_path),
            "--reports-dir", str(reports_dir),
            "--config-dir", str(config_dir),
            *extra,
        ]
        return import_contacts.main(argv, checker=fake_checker(STATUSES if statuses is None else statuses))

    run.reports_dir = reports_dir
    return run


def contacts(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return {row["email"]: dict(row) for row in conn.execute("SELECT * FROM contacts")}
    finally:
        conn.close()


def all_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT * FROM contacts ORDER BY email").fetchall()
    finally:
        conn.close()


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_summary(text):
    blocks, current = {}, None
    for line in text.splitlines():
        if line.startswith("source: "):
            current = blocks.setdefault(line[len("source: "):].split(" (year")[0], {})
        elif line == "total":
            current = blocks.setdefault("total", {})
        elif line.startswith("  ") and current is not None:
            match = re.match(r"^  (.+?):\s+(.*)$", line)
            label, value = match.group(1), match.group(2).strip()
            current[label] = int(value) if value.lstrip("-").isdigit() else value
        elif not line.startswith("  "):
            current = None
    return blocks


def set_tracking(db_path, email):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE contacts SET times_contacted = 2, last_contacted_at = '2026-09-20T10:00:00Z', "
        "bounced = 1, bounced_at = '2026-09-21T10:00:00Z', responded = 1, "
        "responded_at = '2026-09-22T10:00:00Z', opted_out = 1, opted_out_at = '2026-09-23T10:00:00Z' "
        "WHERE email = ?",
        (email,),
    )
    conn.commit()
    conn.close()


TRACKING = ("times_contacted", "last_contacted_at", "bounced", "bounced_at", "responded",
            "responded_at", "opted_out", "opted_out_at", "created_at")


# --- US1: database of addresses valid to be sent -------------------------------------------


def test_us1_stores_only_mail_accepting_unique_addresses(run_import, db_path):
    assert run_import() == 0
    assert set(contacts(db_path)) == STORED


def test_us1_stored_columns(run_import, db_path):
    run_import()
    rows = contacts(db_path)
    ana = rows["ana.perez@example.com"]
    assert (ana["company"], ana["company_key"], ana["contact_name"], ana["city"], ana["tax_id"], ana["area"]) == (
        "INVERSIONES UNO, C.A.", "n:inversiones uno", "", "Caracas", "J123456789", "Comercio")
    assert (ana["classification"], ana["source_file"], ana["source_sheet"], ana["source_row"], ana["source_year"]) == (
        "personal", "ClientesFebrero2020.xls", "Clientes", 2, 2020)
    carla = rows["carla@example.net"]
    assert (carla["contact_name"], carla["city"], carla["source_file"], carla["source_row"], carla["source_year"]) == (
        "Carla Gomez", "Mérida", "Year Book 2009.xlsx", 2, 2009)
    assert rows["marta@example.org"]["city"] == "Villa Inventada"


def test_us1_duplicate_keeps_most_complete_row(run_import, db_path):
    run_import()
    luis = contacts(db_path)["luis@example.com"]
    assert luis["source_row"] == 7 and luis["area"] == "Industria"


def test_us1_same_company_shares_key(run_import, db_path):
    run_import()
    rows = contacts(db_path)
    assert rows["ana.perez@example.com"]["company_key"] == rows["ventas@example.com"]["company_key"]
    assert rows["carla@example.net"]["company_key"] == rows["carlos@example.net"]["company_key"] == "n:grupo cinco"


def test_us1_rejects_report(run_import):
    run_import()
    rejects = read_csv(run_import.reports_dir / "rejects.csv")
    assert [(r["source_file"], r["source_sheet"], r["source_row"], r["email_raw"], r["reason"]) for r in rejects] == [
        ("ClientesFebrero2020.xls", "Clientes", "4", "", "empty"),
        ("ClientesFebrero2020.xls", "Clientes", "5", "no-es-correo", "invalid_format"),
        ("ClientesFebrero2020.xls", "Clientes", "8", "pedro@dead.example", "domain_not_found"),
        ("ClientesFebrero2020.xls", "Clientes", "9", "rosa@nomx.example", "no_mail_server"),
        ("ClientesFebrero2020.xls", "Clientes", "10", "juan@nullmx.example", "null_mx"),
    ]


def test_us1_review_report(run_import):
    run_import()
    review = read_csv(run_import.reports_dir / "review.csv")
    items = {(r["type"], r["source_sheet"], r["source_row"], r["detail"], r["count"]) for r in review}
    assert items == {
        ("city_not_in_mapping", "", "", "Villa Inventada", "1"),
        ("company_contains_at", "1-100", "3", "correo@example.net", "1"),
        ("invalid_token_in_multi_cell", "1-100", "4", "mal@", "1"),
        ("multi_address_cell", "1-100", "2", "carla@example.net; carlos@example.net", "1"),
        ("unverified_domain", "Clientes", "11", "eva@slow.example", "1"),
    }
    assert [r["type"] for r in review] == sorted(r["type"] for r in review)


def test_us1_unverified_address_not_stored(run_import, db_path):
    run_import()
    assert "eva@slow.example" not in contacts(db_path)


def test_us1_source_files_unchanged(run_import, yearbook_xlsx):
    run_import()
    before = run_import.yearbook_path.read_bytes()
    clients_path = run_import.yearbook_path.parent / "ClientesFebrero2020.xls"
    clients_before = clients_path.read_bytes()
    import_contacts.main([
        "--clients", str(clients_path), "--yearbook", str(run_import.yearbook_path),
        "--db", str(run_import.yearbook_path.parent / "other.sqlite3"),
        "--reports-dir", str(run_import.reports_dir),
        "--config-dir", str(ROOT / "config"),
    ], checker=lambda domain: "accepts")
    assert run_import.yearbook_path.read_bytes() == before
    assert clients_path.read_bytes() == clients_before


def test_us1_no_staged_files_left(run_import):
    run_import()
    assert sorted(p.name for p in run_import.reports_dir.iterdir()) == ["rejects.csv", "review.csv"]


# --- US2: tracking fields ------------------------------------------------------------------


def test_us2_new_contacts_start_with_clean_tracking(run_import, db_path):
    run_import()
    for row in contacts(db_path).values():
        assert row["times_contacted"] == 0 and row["last_contacted_at"] is None
        assert (row["bounced"], row["responded"], row["opted_out"]) == (0, 0, 0)
        assert row["bounced_at"] is None and row["responded_at"] is None and row["opted_out_at"] is None


def test_us2_rerun_preserves_tracking_and_refreshes_descriptive(run_import, db_path):
    run_import()
    set_tracking(db_path, "ana.perez@example.com")
    before = {k: contacts(db_path)["ana.perez@example.com"][k] for k in TRACKING}
    clients = base_clients()
    clients["Clientes"][1] = client("J-12345678-9", "INVERSIONES UNO, C.A.", "Valencia", "ana.perez@example.com", "Comercio")
    assert run_import(clients=clients) == 0
    after = contacts(db_path)["ana.perez@example.com"]
    assert {k: after[k] for k in TRACKING} == before
    assert after["city"] == "Valencia"


def test_us2_rerun_adds_new_contact_with_defaults(run_import, db_path):
    run_import()
    clients = base_clients()
    clients["Clientes"].append(client("J-10101010-1", "Nueva Empresa", "Coro", "nuevo@example.com"))
    assert run_import(clients=clients) == 0
    row = contacts(db_path)["nuevo@example.com"]
    assert row["times_contacted"] == 0 and row["bounced"] == 0 and row["source_row"] == 13


def test_us2_stored_contact_whose_domain_now_fails_is_kept(run_import, db_path):
    run_import()
    set_tracking(db_path, "marta@example.org")
    before = contacts(db_path)["marta@example.org"]
    statuses = dict(STATUSES, **{"example.org": "domain_not_found"})
    assert run_import(statuses=statuses) == 0
    assert contacts(db_path)["marta@example.org"] == before
    review = read_csv(run_import.reports_dir / "review.csv")
    assert ("stored_domain_now_fails", "marta@example.org (domain_not_found)") in {
        (r["type"], r["detail"]) for r in review
    }
    rejects = read_csv(run_import.reports_dir / "rejects.csv")
    assert "marta@example.org" not in {r["email_raw"] for r in rejects}


def test_us2_identical_rerun_leaves_identical_contents(run_import, db_path):
    run_import()
    first = all_rows(db_path)
    assert run_import() == 0
    assert all_rows(db_path) == first


def test_us2_failure_during_upsert_changes_nothing(run_import, db_path, monkeypatch):
    run_import()
    rows_before = all_rows(db_path)
    rejects_before = (run_import.reports_dir / "rejects.csv").read_bytes()
    review_before = (run_import.reports_dir / "review.csv").read_bytes()
    real_upsert = store.upsert_contacts

    def failing_upsert(conn, values, now):
        real_upsert(conn, values, now)
        raise RuntimeError("simulated failure after writing")

    monkeypatch.setattr(store, "upsert_contacts", failing_upsert)
    clients = base_clients()
    clients["Clientes"].append(client("J-10101010-1", "Nueva Empresa", "Coro", "nuevo@example.com"))
    assert run_import(clients=clients) == 2
    assert all_rows(db_path) == rows_before
    assert (run_import.reports_dir / "rejects.csv").read_bytes() == rejects_before
    assert (run_import.reports_dir / "review.csv").read_bytes() == review_before
    assert sorted(p.name for p in run_import.reports_dir.iterdir()) == ["rejects.csv", "review.csv"]


def test_us2_contact_missing_from_sources_is_kept_and_counted(run_import, db_path, capsys):
    run_import()
    capsys.readouterr()
    clients = base_clients()
    del clients["Clientes"][11]  # marta@example.org row
    assert run_import(clients=clients) == 0
    assert "marta@example.org" in contacts(db_path)
    assert parse_summary(capsys.readouterr().out)["total"]["contacts not in sources"] == 1


# --- US3: classification -------------------------------------------------------------------


def test_us3_classification_stored(run_import, db_path):
    run_import()
    labels = {email: row["classification"] for email, row in contacts(db_path).items()}
    assert labels.pop("ventas@example.com") == "generic"
    assert set(labels.values()) == {"personal"}


def test_us3_role_word_edit_reclassifies_existing_contact(run_import, db_path, config_dir, monkeypatch, capsys):
    run_import()
    set_tracking(db_path, "luis@example.com")
    before = {k: contacts(db_path)["luis@example.com"][k] for k in TRACKING}
    with open(config_dir / "role_words.txt", "a", encoding="utf-8") as handle:
        handle.write("luis\n")
    monkeypatch.setattr(store, "utc_now", lambda: "2030-01-01T00:00:00Z")
    capsys.readouterr()
    assert run_import() == 0
    after = contacts(db_path)["luis@example.com"]
    assert after["classification"] == "generic"
    assert after["updated_at"] == "2030-01-01T00:00:00Z"
    assert {k: after[k] for k in TRACKING} == before
    assert parse_summary(capsys.readouterr().out)["total"]["existing updated"] == 1


# --- US4: summary and error output ---------------------------------------------------------


def test_us4_summary_counts_reconcile(run_import, capsys):
    assert run_import() == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "import_contacts: done"
    blocks = parse_summary(out)
    clients = blocks["ClientesFebrero2020.xls"]
    yearbook = blocks["Year Book 2009.xlsx"]
    total = blocks["total"]
    assert clients == {
        "sheets skipped": "SQL", "rows read": 11, "extra from split cells": 0, "rejected (format)": 2,
        "merged duplicates": 1, "duplicate conflicts": 0, "new contacts": 4, "existing updated": 0,
        "existing unchanged": 0, "rejected (domain)": 3, "unverified": 1, "personal": 3, "generic": 1,
        "missing city": 0, "distinct companies": 3,
    }
    assert yearbook == {
        "sheets skipped": "14-100", "rows read": 3, "extra from split cells": 1, "rejected (format)": 0,
        "merged duplicates": 0, "duplicate conflicts": 0, "new contacts": 4, "existing updated": 0,
        "existing unchanged": 0, "rejected (domain)": 0, "unverified": 0, "personal": 4, "generic": 0,
        "missing city": 1, "distinct companies": 3,
    }
    assert total["sheets skipped"] == "SQL, 14-100"
    for label, value in clients.items():
        if isinstance(value, int) and label != "distinct companies":
            assert total[label] == value + yearbook[label]
    assert total["distinct companies"] == 6
    assert total["contacts not in sources"] == 0
    assert re.search(r"^database: .*b2b\.sqlite3 \(8 contacts\)$", out, re.M)
    assert re.search(r"^reports:  .*rejects\.csv \(5 rows\), .*review\.csv \(5 rows\)$", out, re.M)


def test_us4_output_never_contains_contact_values(run_import, capsys):
    run_import()
    run_import(statuses=dict(STATUSES, **{"example.org": "domain_not_found"}))
    captured = capsys.readouterr()
    text = captured.out + captured.err
    for value in CONTACT_VALUES:
        assert value not in text, value


def test_us4_missing_header_exits_1_and_writes_nothing(run_import, db_path, capsys):
    yearbook = base_yearbook()
    yearbook["1-100"][0] = ["EMPRESA", "CONTACTO", "CIUDAD"]
    assert run_import(yearbook=yearbook) == 1
    err = capsys.readouterr().err
    assert err.startswith("import_contacts: error: ") and "CORREO" in err
    assert not db_path.exists()
    assert not run_import.reports_dir.exists()


def test_us4_bad_city_mapping_exits_1(run_import, config_dir, capsys):
    (config_dir / "cities.csv").write_text("ciudad,nombre\n", encoding="utf-8")
    assert run_import() == 1
    assert "expected header 'variant,canonical'" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [("--dns-workers", "0"), ("--dns-timeout", "31")])
def test_us4_invalid_option_exits_1(run_import, db_path, capsys, extra):
    assert run_import(extra=extra) == 1
    assert capsys.readouterr().err.startswith("import_contacts: error: ")
    assert not db_path.exists()


def test_us4_newer_schema_exits_2(run_import, db_path, capsys):
    conn = store.connect(db_path)
    conn.execute("PRAGMA user_version = 5")
    conn.close()
    assert run_import() == 2
    assert "schema version 5 is newer" in capsys.readouterr().err
