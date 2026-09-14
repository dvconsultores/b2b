"""Shared pytest fixtures: synthetic inputs only, network disabled (spec 001 D14, spec 002 D16)."""
from __future__ import annotations

import re
import shutil
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dns.resolver
import openpyxl
import pytest
import xlrd

from b2b import store
from b2b.store import ContactValues

ROOT = Path(__file__).resolve().parents[1]

TRACKING_KEYS = ("times_contacted", "last_contacted_at", "bounced", "bounced_at", "responded",
                 "responded_at", "opted_out", "opted_out_at")


def _network_disabled(*args, **kwargs):
    raise RuntimeError("network disabled in tests")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket, "socket", _network_disabled)
    monkeypatch.setattr(dns.resolver.Resolver, "resolve", _network_disabled)


@pytest.fixture
def fake_checker():
    def make(statuses: dict[str, str]):
        def check(domain: str) -> str:
            return statuses.get(domain, "accepts")

        return check

    return make


@pytest.fixture
def yearbook_xlsx(tmp_path):
    def make(sheets: dict[str, list[list[object]]], name: str = "Year Book 2009.xlsx") -> Path:
        workbook = openpyxl.Workbook()
        workbook.remove(workbook.active)
        for title, rows in sheets.items():
            sheet = workbook.create_sheet(title)
            for row in rows:
                sheet.append(row)
        path = tmp_path / name
        workbook.save(path)
        return path

    return make


class _StubSheet:
    def __init__(self, name: str, rows: list[list[object]]):
        self.name = name
        self._rows = [list(row) for row in rows]
        self.nrows = len(self._rows)

    def row_values(self, index: int) -> list[object]:
        return list(self._rows[index])


class _StubBook:
    def __init__(self, sheets: dict[str, list[list[object]]]):
        self._sheets = [_StubSheet(name, rows) for name, rows in sheets.items()]

    def sheets(self) -> list[_StubSheet]:
        return list(self._sheets)


@pytest.fixture
def stub_xls(monkeypatch, tmp_path):
    books: dict[str, _StubBook] = {}

    def fake_open_workbook(filename, *args, **kwargs):
        return books[str(filename)]

    monkeypatch.setattr(xlrd, "open_workbook", fake_open_workbook)

    def make(sheets: dict[str, list[list[object]]], name: str = "ClientesFebrero2020.xls") -> Path:
        path = tmp_path / name
        path.write_bytes(b"")
        books[str(path)] = _StubBook(sheets)
        return path

    return make


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "data" / "b2b.sqlite3"


# --- spec 002 fixtures -------------------------------------------------------------------------


class SmtpLog:
    def __init__(self, script):
        self.script = list(script or [])
        self.messages: list[tuple[str, object, object]] = []
        self.connects = 0
        self.logins = 0
        self.quits = 0
        self.login_error: BaseException | None = None


class FakeSMTP:
    def __init__(self, log: SmtpLog):
        self._log = log

    def login(self, user, password):
        self._log.logins += 1
        if self._log.login_error is not None:
            raise self._log.login_error

    def sendmail(self, from_addr, to_addrs, msg):
        self._log.messages.append((from_addr, to_addrs, msg))
        item = self._log.script.pop(0) if self._log.script else None
        if isinstance(item, BaseException):
            raise item
        return item if isinstance(item, dict) else {}

    def quit(self):
        self._log.quits += 1


@pytest.fixture
def fake_smtp():
    def make(script: list[object] | None = None):
        log = SmtpLog(script)

        def factory(settings):
            log.connects += 1
            return FakeSMTP(log)

        return factory, log

    return make


class FakeClock:
    def __init__(self, start: datetime):
        self.current = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current = self.current + timedelta(seconds=seconds)


@pytest.fixture
def fake_clock():
    # Monday 2026-09-14 09:00 in America/Caracas (UTC-4).
    return FakeClock(datetime(2026, 9, 14, 13, 0, 0, tzinfo=timezone.utc))


SEND_ENV_DEFAULTS = {
    "HOST_EMAIL": "smtp.example.com",
    "PORT_EMAIL": "465",
    "USER_EMAIL": "usuario-prueba",
    "PASS_EMAIL": "clave-de-prueba",
    "SENDER_EMAIL": "remitente@example.com",
    "SMTP_FROM_NAME": "Ana Remitente",
    "TEST_RECIPIENTS": "prueba1@example.org,prueba2@example.net",
}


@pytest.fixture
def send_env(tmp_path):
    def make(**overrides) -> Path:
        values = dict(SEND_ENV_DEFAULTS)
        for key, value in overrides.items():
            if value is None:
                values.pop(key, None)
            else:
                values[key] = value
        path = tmp_path / ".env"
        path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
        return path

    return make


@pytest.fixture
def campaign_files(tmp_path):
    def make(**overrides) -> Path:
        config_dir = tmp_path / "config"
        (config_dir / "templates").mkdir(parents=True, exist_ok=True)
        template = config_dir / "templates" / "primer_contacto.txt"
        shutil.copyfile(ROOT / "config" / "templates" / "primer_contacto.txt", template)
        text = (ROOT / "config" / "campaign.toml").read_text(encoding="utf-8")
        text = re.sub(r'(?m)^template = .*$', f'template = "{template.as_posix()}"', text)
        for key, literal in overrides.items():
            pattern = rf"(?m)^{re.escape(key)} = .*$"
            assert re.search(pattern, text), f"no top-level key {key} in campaign.toml"
            text = re.sub(pattern, f"{key} = {literal}", text)
        path = config_dir / "campaign.toml"
        path.write_text(text, encoding="utf-8")
        return path

    return make


@pytest.fixture
def contacts_db(db_path):
    def make(rows: list[dict]) -> list[int]:
        conn = store.connect(db_path)
        try:
            store.ensure_schema(conn)
            values = []
            for index, row in enumerate(rows):
                base = dict(
                    company=f"Empresa {index}",
                    company_key=f"n:empresa {index}",
                    contact_name="",
                    city="Caracas",
                    tax_id="",
                    area="",
                    classification="personal",
                    source_file="ClientesFebrero2020.xls",
                    source_sheet="Clientes",
                    source_row=index + 2,
                    source_year=2020,
                )
                base.update({k: v for k, v in row.items() if k not in TRACKING_KEYS})
                values.append(ContactValues(**base))
            with store.transaction(conn):
                store.upsert_contacts(conn, values, "2026-09-13T12:00:00Z")
            ids = []
            for row in rows:
                contact_id = conn.execute("SELECT id FROM contacts WHERE email = ?", (row["email"],)).fetchone()[0]
                tracking = {k: v for k, v in row.items() if k in TRACKING_KEYS}
                if tracking:
                    assignments = ", ".join(f"{k} = ?" for k in tracking)
                    conn.execute(f"UPDATE contacts SET {assignments} WHERE id = ?", (*tracking.values(), contact_id))
                ids.append(contact_id)
            return ids
        finally:
            conn.close()

    return make
