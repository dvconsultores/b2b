"""End-to-end tests for the first-email command on synthetic data (spec 002 US1–US4)."""
from __future__ import annotations

import random
import re
import smtplib
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import dns.exception
import dns.resolver
import pytest

from b2b import tracking
from b2b.send_first_email import main

CAMPAIGN = "primer-contacto-2026-b"

BASE_CONTACTS = [
    {"email": "ana@example.com", "company": "INVERSIONES UNO, C.A.", "company_key": "n:inversiones uno",
     "contact_name": "ING. ANA PÉREZ", "city": "Caracas"},
    {"email": "luis@example.org", "company": "Comercial Dos", "company_key": "n:comercial dos",
     "contact_name": "", "city": ""},
    {"email": "tienda@example.com", "company": "Tienda.com", "company_key": "n:tienda com", "city": "Maracay"},
    {"email": "info@example.com", "company": "Grupo Cuatro", "company_key": "n:grupo cuatro",
     "classification": "generic"},
    {"email": "carla@example.net", "company": "", "company_key": "e:carla@example.net", "contact_name": "Carla",
     "city": "Mérida", "source_year": 2009, "source_file": "Year Book 2009.xlsx", "source_sheet": "1-100"},
]

CONTACT_VALUES = ["ana@example.com", "luis@example.org", "tienda@example.com", "info@example.com",
                  "carla@example.net", "INVERSIONES UNO", "Inversiones Uno", "Comercial Dos", "Tienda.com",
                  "Grupo Cuatro", "ANA PÉREZ", "Ana", "Carla", "Mérida", "Maracay"]


class _Txt:
    def __init__(self, text: str):
        self.strings = (text.encode(),)


def fake_resolver(dmarc: str = "present"):
    class Resolver:
        lifetime = None

        def resolve(self, name, rdtype):
            if name.startswith("_dmarc."):
                if dmarc == "present":
                    return [_Txt("v=DMARC1; p=none")]
                if dmarc == "missing":
                    raise dns.resolver.NXDOMAIN()
                raise dns.exception.Timeout()
            return [_Txt("v=spf1 include:amazonses.com ~all")]

    return Resolver()


def forbidden_smtp(settings):
    raise AssertionError("SMTP must not be used in this mode")


@pytest.fixture
def setup(tmp_path, contacts_db, send_env, campaign_files, db_path):
    def make(extra_contacts=(), env=None, **campaign_overrides):
        ids = contacts_db(BASE_CONTACTS + list(extra_contacts))
        return SimpleNamespace(
            ids=dict(zip([c["email"] for c in BASE_CONTACTS + list(extra_contacts)], ids)),
            env=send_env(**(env or {})),
            config=campaign_files(**campaign_overrides),
            db=db_path,
            previews=tmp_path / "previews",
        )

    return make


def run(s, mode, clock, smtp_factory=forbidden_smtp, dmarc="present", answer=CAMPAIGN, extra=()):
    argv = ["--mode", mode, "--config", str(s.config), "--db", str(s.db), "--env", str(s.env),
            "--previews-dir", str(s.previews), *extra]
    return main(argv, smtp_factory=smtp_factory, resolver=fake_resolver(dmarc), now=clock.now,
                sleep=clock.sleep, ask=lambda _prompt: answer, rng=random.Random(0))


def dump(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for table in ("contacts", "runs", "send_attempts")}
    finally:
        conn.close()


def query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def execute(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def summary_of(text):
    values = {}
    for line in text.splitlines():
        if line.startswith("send_first_email: "):
            values["_result"] = line.split(" ", 2)[2]
        match = re.match(r"^  ([^:]+):\s+(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def recipients(log):
    return [to_addrs[0] for _from, to_addrs, _msg in log.messages]


def bodies(log):
    from email import message_from_bytes
    from email.policy import default

    return [message_from_bytes(msg, policy=default) for _f, _t, msg in log.messages]


def seed_sent_campaign(db_path, contact_ids, created="2026-09-13T13:00:00Z"):
    conn = sqlite3.connect(db_path)
    run_id = conn.execute(
        "INSERT INTO runs (kind, campaign, step, started_at, finished_at, stop_reason) "
        "VALUES ('send_production', ?, 1, '2026-09-13T13:00:00Z', '2026-09-13T18:00:00Z', 'batch_complete')",
        (CAMPAIGN,)).lastrowid
    for index, contact_id in enumerate(contact_ids):
        conn.execute(
            "INSERT INTO send_attempts (run_id, contact_id, campaign, step, status, smtp_code, message_id, "
            "created_at, finished_at) VALUES (?, ?, ?, 1, 'accepted', 250, ?, ?, '2026-09-13T13:00:01Z')",
            (run_id, contact_id, CAMPAIGN, f"<seed{index}@example.com>", created))
    conn.execute("INSERT INTO runs (kind, started_at, finished_at) VALUES "
                 "('inbox', '2026-09-13T19:00:00Z', '2026-09-13T19:10:00Z')")
    conn.commit()
    conn.close()


def sent_contacts(count, bounced=0):
    rows = []
    for index in range(count):
        row = {"email": f"sent{index}@example.com", "company_key": f"n:sent {index}",
               "times_contacted": 1, "last_contacted_at": "2026-09-13T13:00:01Z"}
        if index < bounced:
            row.update(bounced=1, bounced_at="2026-09-13T20:00:00Z")
        rows.append(row)
    return rows


# --- US1: preview ---------------------------------------------------------------------------------


def test_preview_writes_file_and_changes_nothing(setup, fake_clock, capsys):
    s = setup()
    before = dump(s.db)
    assert run(s, "preview", fake_clock) == 0
    assert dump(s.db) == before
    files = list(s.previews.iterdir())
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Emails: 3" in text
    assert text.index("To: ana@example.com") < text.index("To: luis@example.org") < text.index("To: carla@example.net")
    assert "tienda@example.com" not in text and "info@example.com" not in text
    assert "Subject: Pregunta rápida sobre la nómina de Inversiones Uno, C.A." in text
    assert "Hola Ana," in text
    assert "Vi que Inversiones Uno, C.A. está en Caracas" in text
    assert "Quería hacerle una pregunta rápida sobre la nómina de Comercial Dos" in text
    assert "Vi que su empresa está en Mérida" in text
    assert "Saludos,\nAna Remitente\n\nP. D.: Si no es de su interés" in text
    values = summary_of(capsys.readouterr().out)
    assert values["_result"] == "done"
    assert (values["eligible contacts"], values["skipped same company"], values["skipped rendered link"],
            values["selected"], values["previewed"]) == ("4", "0", "1", "3", "3")
    assert values["preview"] if "preview" in values else True


def test_preview_respects_batch_limit(setup, fake_clock, capsys):
    s = setup(batch_limit="2")
    assert run(s, "preview", fake_clock) == 0
    assert summary_of(capsys.readouterr().out)["selected"] == "2"


def test_preview_output_has_no_contact_values(setup, fake_clock, capsys):
    s = setup()
    run(s, "preview", fake_clock)
    captured = capsys.readouterr()
    for value in CONTACT_VALUES:
        assert value not in captured.out + captured.err, value


def test_template_with_link_exits_1(setup, fake_clock, capsys):
    s = setup()
    template = s.config.parent / "templates" / "primer_contacto.txt"
    template.write_text(template.read_text(encoding="utf-8") + "\nVisite www.ejemplo.com\n", encoding="utf-8")
    assert run(s, "preview", fake_clock) == 1
    assert "link or domain not allowed in template" in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["preview", "test", "send"])
def test_launch_price_passed_exits_1(setup, fake_clock, capsys, mode):
    s = setup(launch_price_end="2026-09-01")
    assert run(s, mode, fake_clock) == 1
    assert "launch_price_end 2026-09-01 has passed" in capsys.readouterr().err


def test_force_flag_outside_send_mode_exits_1(setup, fake_clock, capsys):
    s = setup()
    assert run(s, "preview", fake_clock, extra=("--force-no-dmarc",)) == 1
    assert capsys.readouterr().err.startswith("send_first_email: error: ")


def test_newer_schema_exits_2(setup, fake_clock):
    s = setup()
    execute(s.db, "PRAGMA user_version = 5")
    assert run(s, "preview", fake_clock) == 2


def test_missing_database_exits_2(setup, fake_clock, tmp_path):
    s = setup()
    s.db = tmp_path / "missing.sqlite3"
    assert run(s, "preview", fake_clock) == 2
    assert not s.db.exists()


# --- US2: test send -------------------------------------------------------------------------------


def test_test_mode_sends_synthetic_samples_only(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    before = dump(s.db)
    factory, log = fake_smtp()
    assert run(s, "test", fake_clock, smtp_factory=factory) == 0
    assert dump(s.db) == before
    assert recipients(log) == ["prueba1@example.org", "prueba2@example.net", "prueba1@example.org"]
    messages = bodies(log)
    assert all(str(m["Subject"]).startswith("[PRUEBA] ") for m in messages)
    contents = [m.get_content() for m in messages]
    assert all("Empresa Ejemplo, C.A." in c for c in contents)
    assert contents[0].startswith("Hola Ana,") and "está en Caracas" in contents[0]
    assert contents[1].startswith("Hola,")
    assert "sobre la nómina de Empresa Ejemplo, C.A." in contents[2]
    joined = "\n".join(contents)
    for value in ("ana@example.com", "Comercial Dos", "Mérida", "INVERSIONES UNO"):
        assert value not in joined
    values = summary_of(capsys.readouterr().out)
    assert (values["_result"], values["test emails sent"], values["DMARC"], values["SPF"]) == (
        "done", "3", "present (p=none)", "includes_ses")


def test_test_mode_requires_test_recipients(setup, fake_clock, capsys):
    s = setup(env={"TEST_RECIPIENTS": None})
    assert run(s, "test", fake_clock) == 1
    assert "missing TEST_RECIPIENTS" in capsys.readouterr().err


def test_test_mode_stops_on_throttling(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp([smtplib.SMTPDataError(454, b"Throttling failure")])
    assert run(s, "test", fake_clock, smtp_factory=factory) == 4
    values = summary_of(capsys.readouterr().out)
    assert (values["_result"], values["stop reason"], values["test emails sent"]) == ("stopped", "provider_throttled", "0")
    assert len(log.messages) == 1


def test_test_mode_not_blocked_by_missing_dmarc(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, _log = fake_smtp()
    assert run(s, "test", fake_clock, smtp_factory=factory, dmarc="missing") == 0
    assert summary_of(capsys.readouterr().out)["DMARC"] == "missing"


# --- US3: production ------------------------------------------------------------------------------


def test_wrong_confirmation_sends_nothing(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory, answer="si") == 3
    out = capsys.readouterr().out
    assert "recipients:      3" in out and "hourly cap:      20 per hour" in out
    assert "send window:     mon–fri 08:00–17:00 America/Caracas" in out
    assert log.messages == []
    assert query(s.db, "SELECT COUNT(*) FROM runs")[0][0] == 0


def test_batch_is_sent_and_recorded(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory) == 0
    assert recipients(log) == ["ana@example.com", "luis@example.org", "carla@example.net"]
    statuses = query(s.db, "SELECT c.email, a.status, a.message_id IS NOT NULL FROM send_attempts a "
                           "JOIN contacts c ON c.id = a.contact_id ORDER BY a.id")
    assert statuses == [("ana@example.com", "accepted", 1), ("luis@example.org", "accepted", 1),
                        ("carla@example.net", "accepted", 1)]
    contacted = dict(query(s.db, "SELECT email, times_contacted FROM contacts"))
    assert contacted == {"ana@example.com": 1, "luis@example.org": 1, "carla@example.net": 1,
                         "tienda@example.com": 0, "info@example.com": 0}
    [(stop_reason, finished, forced)] = query(s.db, "SELECT stop_reason, finished_at IS NOT NULL, forced_no_dmarc FROM runs")
    assert (stop_reason, finished, forced) == ("batch_complete", 1, 0)
    assert len(fake_clock.sleeps) == 2 and all(144 <= seconds <= 216 for seconds in fake_clock.sleeps)
    values = summary_of(capsys.readouterr().out)
    assert (values["_result"], values["accepted"], values["stop reason"]) == ("done", "3", "batch_complete")


def test_permanent_rejection_marks_contact_bounced(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, _log = fake_smtp([smtplib.SMTPRecipientsRefused({"ana@example.com": (550, b"no such user")})])
    assert run(s, "send", fake_clock, smtp_factory=factory) == 0
    [(bounced, times)] = query(s.db, "SELECT bounced, times_contacted FROM contacts WHERE email = 'ana@example.com'")
    assert (bounced, times) == (1, 0)
    values = summary_of(capsys.readouterr().out)
    assert (values["accepted"], values["permanent rejections"]) == ("2", "1")
    assert values["campaign bounce rate"] == "33.3% (1 of 3)"


def test_bounce_threshold_stops_before_next_email(setup, fake_clock, fake_smtp, capsys):
    s = setup(extra_contacts=sent_contacts(19))
    seed_sent_campaign(s.db, [s.ids[f"sent{i}@example.com"] for i in range(19)])
    factory, log = fake_smtp([smtplib.SMTPRecipientsRefused({"ana@example.com": (550, b"unknown")})])
    assert run(s, "send", fake_clock, smtp_factory=factory) == 4
    assert recipients(log) == ["ana@example.com"]
    values = summary_of(capsys.readouterr().out)
    assert (values["stop reason"], values["campaign bounce rate"]) == ("bounce_threshold", "5.0% (1 of 20)")


def test_bounce_rate_already_above_threshold_refuses(setup, fake_clock, fake_smtp):
    s = setup(extra_contacts=sent_contacts(20, bounced=1))
    seed_sent_campaign(s.db, [s.ids[f"sent{i}@example.com"] for i in range(20)])
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory) == 3
    assert log.messages == []


def test_crash_never_resends_contact(setup, fake_clock, fake_smtp):
    s = setup()
    factory, _log = fake_smtp([KeyboardInterrupt()])
    assert run(s, "send", fake_clock, smtp_factory=factory) == 130
    assert query(s.db, "SELECT status FROM send_attempts") == [("pending",)]
    assert query(s.db, "SELECT stop_reason, finished_at IS NOT NULL FROM runs") == [("interrupted", 1)]

    execute(s.db, "INSERT INTO runs (kind, started_at, finished_at) VALUES ('inbox', ?, ?)",
            ("2026-09-14T13:20:00Z", "2026-09-14T13:30:00Z"))
    fake_clock.sleep(3600)
    factory2, log2 = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory2) == 0
    assert "ana@example.com" not in recipients(log2)
    assert recipients(log2) == ["luis@example.org", "carla@example.net"]
    [(status, kind)] = query(s.db, "SELECT a.status, a.error_kind FROM send_attempts a JOIN contacts c "
                                   "ON c.id = a.contact_id WHERE c.email = 'ana@example.com'")
    assert (status, kind) == ("unknown", "interrupted")
    assert query(s.db, "SELECT times_contacted FROM contacts WHERE email = 'ana@example.com'") == [(0,)]


def test_hourly_cap_never_exceeded(setup, fake_clock, fake_smtp):
    s = setup(hourly_cap="2")
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory) == 0
    assert len(log.messages) == 3
    created = [datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ")
               for row in query(s.db, "SELECT created_at FROM send_attempts ORDER BY created_at")]
    for moment in created:
        in_hour = [other for other in created if 0 <= (moment - other).total_seconds() < 3600]
        assert len(in_hour) <= 2


def test_window_closing_stops_batch(setup, fake_clock, fake_smtp, capsys):
    s = setup(hourly_cap="1")
    fake_clock.current = datetime(2026, 9, 14, 20, 50, tzinfo=timezone.utc)  # Monday 16:50 Caracas
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory) == 4
    assert len(log.messages) == 1
    assert summary_of(capsys.readouterr().out)["stop reason"] == "window_closed"


def test_launch_price_passing_stops_batch(setup, fake_clock, fake_smtp, capsys):
    s = setup(launch_price_end="2026-09-14", send_days='["mon", "tue", "wed", "thu", "fri", "sat", "sun"]',
              send_start='"00:00"', send_end='"23:59"')
    fake_clock.current = datetime(2026, 9, 15, 3, 58, tzinfo=timezone.utc)  # 2026-09-14 23:58 Caracas
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory) == 4
    assert len(log.messages) == 1
    assert summary_of(capsys.readouterr().out)["stop reason"] == "launch_price_ended"


def test_consecutive_temporary_failures_stop(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    deferred = [smtplib.SMTPRecipientsRefused({"x": (450, b"later")}) for _ in range(3)]
    factory, log = fake_smtp(deferred)
    assert run(s, "send", fake_clock, smtp_factory=factory) == 4
    assert len(log.messages) == 3
    values = summary_of(capsys.readouterr().out)
    assert (values["stop reason"], values["temporary failures"]) == ("temporary_failures", "3")
    assert query(s.db, "SELECT SUM(times_contacted), SUM(bounced) FROM contacts") == [(0, 0)]


def test_provider_throttling_stops(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp([smtplib.SMTPDataError(454, b"Maximum sending rate exceeded")])
    assert run(s, "send", fake_clock, smtp_factory=factory) == 4
    assert len(log.messages) == 1
    assert summary_of(capsys.readouterr().out)["stop reason"] == "provider_throttled"
    assert query(s.db, "SELECT SUM(bounced) FROM contacts") == [(0,)]


def test_second_batch_waits_for_inbox_processing(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory) == 0
    capsys.readouterr()
    assert run(s, "send", fake_clock, smtp_factory=factory) == 3
    assert "batch hold" in capsys.readouterr().err
    assert len(log.messages) == 3
    execute(s.db, "INSERT INTO runs (kind, started_at, finished_at) VALUES ('inbox', ?, ?)",
            ("2026-09-14T23:00:00Z", "2026-09-14T23:30:00Z"))
    assert run(s, "send", fake_clock, smtp_factory=factory) == 0
    assert summary_of(capsys.readouterr().out)["_result"] == "nothing_to_send"


def test_concurrent_run_refused(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    with tracking.send_lock(s.db):
        assert run(s, "send", fake_clock, smtp_factory=factory) == 3
    assert "another send run is active" in capsys.readouterr().err
    assert log.connects == 0


def test_login_failure_exits_1(setup, fake_clock, fake_smtp):
    s = setup()
    factory, log = fake_smtp()
    log.login_error = smtplib.SMTPAuthenticationError(535, b"invalid")
    assert run(s, "send", fake_clock, smtp_factory=factory) == 1
    assert log.messages == [] and query(s.db, "SELECT COUNT(*) FROM runs") == [(0,)]


def test_outside_window_at_start(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    fake_clock.current = datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc)  # Saturday 10:00 Caracas
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory) == 0
    values = summary_of(capsys.readouterr().out)
    assert (values["_result"], values["next window opens"]) == ("outside_window", "2026-09-21 08:00 America/Caracas")
    assert log.messages == []


def test_production_output_has_no_contact_values(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, _log = fake_smtp([smtplib.SMTPRecipientsRefused({"ana@example.com": (550, b"ana@example.com unknown")})])
    run(s, "send", fake_clock, smtp_factory=factory)
    captured = capsys.readouterr()
    for value in CONTACT_VALUES + ["clave-de-prueba", "unknown"]:
        if value == "unknown":
            continue  # the label "unknown outcome" is part of the summary
        assert value not in captured.out + captured.err, value


# --- US4: DMARC gate ------------------------------------------------------------------------------


@pytest.mark.parametrize("dmarc", ["missing", "unverified"])
def test_dmarc_not_present_refuses(setup, fake_clock, fake_smtp, capsys, dmarc):
    s = setup()
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory, dmarc=dmarc) == 3
    assert "DMARC not present for sender domain" in capsys.readouterr().err
    assert log.messages == [] and query(s.db, "SELECT COUNT(*) FROM runs") == [(0,)]


def test_force_no_dmarc_continues_and_is_recorded(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory, dmarc="missing", extra=("--force-no-dmarc",)) == 0
    out = capsys.readouterr().out
    assert "forced no DMARC: yes" in out
    assert summary_of(out)["forced no DMARC"] == "yes"
    assert query(s.db, "SELECT forced_no_dmarc FROM runs") == [(1,)]
    assert len(log.messages) == 3


def test_force_flag_recorded_only_when_needed(setup, fake_clock, fake_smtp):
    s = setup()
    factory, _log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory, extra=("--force-no-dmarc",)) == 0
    assert query(s.db, "SELECT forced_no_dmarc FROM runs") == [(0,)]


# --- unattended runs (Docker) ---------------------------------------------------------------------


def never_ask(_prompt):
    raise AssertionError("must not prompt when --confirm is given")


def run_unattended(s, clock, smtp_factory, *extra, dmarc="present"):
    argv = ["--mode", "send", "--config", str(s.config), "--db", str(s.db), "--env", str(s.env),
            "--previews-dir", str(s.previews), *extra]
    return main(argv, smtp_factory=smtp_factory, resolver=fake_resolver(dmarc), now=clock.now,
                sleep=clock.sleep, ask=never_ask, rng=random.Random(0))


def test_confirm_option_sends_without_prompt(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN) == 0
    assert recipients(log) == ["ana@example.com", "luis@example.org", "carla@example.net"]
    out = capsys.readouterr().out
    assert "recipients:      3" in out and "confirmation supplied at launch" in out


def test_confirm_option_with_wrong_name_refuses(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    assert run_unattended(s, fake_clock, factory, "--confirm", "otra-campana") == 3
    assert "does not match the campaign name" in capsys.readouterr().err
    assert log.messages == [] and query(s.db, "SELECT COUNT(*) FROM runs") == [(0,)]


@pytest.mark.parametrize("extra", [("--confirm", CAMPAIGN), ("--wait-for-window",), ("--notify",)])
def test_send_only_options_rejected_in_other_modes(setup, fake_clock, capsys, extra):
    s = setup()
    assert run(s, "preview", fake_clock, extra=extra) == 1
    assert "only allowed with --mode send" in capsys.readouterr().err


def test_wait_for_window_at_start(setup, fake_clock, fake_smtp):
    s = setup()
    fake_clock.current = datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc)  # Saturday 10:00 Caracas
    factory, log = fake_smtp()
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN, "--wait-for-window") == 0
    assert len(log.messages) == 3
    first = query(s.db, "SELECT MIN(created_at) FROM send_attempts")[0][0]
    assert first == "2026-09-21T12:00:00Z"  # Monday 08:00 Caracas
    assert fake_clock.sleeps[0] == (datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
                                    - datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc)).total_seconds()


def test_wait_for_window_resumes_next_day(setup, fake_clock, fake_smtp):
    s = setup(hourly_cap="1")
    fake_clock.current = datetime(2026, 9, 14, 20, 50, tzinfo=timezone.utc)  # Monday 16:50 Caracas
    factory, log = fake_smtp()
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN, "--wait-for-window") == 0
    assert len(log.messages) == 3
    created = [row[0] for row in query(s.db, "SELECT created_at FROM send_attempts ORDER BY id")]
    assert created[0] == "2026-09-14T20:50:00Z"
    assert created[1] >= "2026-09-15T12:00:00Z"  # Tuesday 08:00 Caracas or later
    assert query(s.db, "SELECT stop_reason FROM runs") == [("batch_complete",)]


def test_notify_emails_counts_only_summary(setup, fake_clock, fake_smtp):
    s = setup()
    factory, log = fake_smtp()
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN, "--notify") == 0
    assert recipients(log)[:3] == ["ana@example.com", "luis@example.org", "carla@example.net"]
    assert recipients(log)[3:] == ["prueba1@example.org", "prueba2@example.net"]
    notice = bodies(log)[3]
    assert str(notice["Subject"]) == f"[b2b] {CAMPAIGN}: done (batch_complete)"
    content = notice.get_content()
    assert "accepted:" in content and "stop reason:" in content
    for value in CONTACT_VALUES:
        assert value not in content, value


def test_notify_after_stop(setup, fake_clock, fake_smtp):
    s = setup()
    factory, log = fake_smtp([smtplib.SMTPDataError(454, b"Throttling failure")])
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN, "--notify") == 4
    subjects = [str(m["Subject"]) for m in bodies(log)[1:]]
    assert subjects == [f"[b2b] {CAMPAIGN}: stopped (provider_throttled)"] * 2


def test_notify_requires_test_recipients(setup, fake_clock, fake_smtp, capsys):
    s = setup(env={"TEST_RECIPIENTS": None})
    factory, log = fake_smtp()
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN, "--notify") == 1
    assert "missing TEST_RECIPIENTS" in capsys.readouterr().err
    assert log.connects == 0


def test_manual_inbox_check_releases_batch_hold(setup, fake_clock, fake_smtp, capsys):
    from b2b.mark_inbox_checked import main as mark_main

    s = setup(extra_contacts=[{"email": "nuevo@example.net", "company_key": "n:nuevo"}])
    factory, log = fake_smtp()
    execute(s.db, "UPDATE contacts SET classification = 'generic' WHERE email = 'nuevo@example.net'")
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN) == 0
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN) == 3
    assert "mark_inbox_checked" in capsys.readouterr().err
    fake_clock.sleep(600)
    execute(s.db, "UPDATE contacts SET classification = 'personal' WHERE email = 'nuevo@example.net'")
    assert mark_main(["--db", str(s.db)], now=fake_clock.now) == 0
    assert run_unattended(s, fake_clock, factory, "--confirm", CAMPAIGN) == 0
    assert recipients(log)[-1] == "nuevo@example.net"


def test_dmarc_present_reported(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, _log = fake_smtp()
    assert run(s, "send", fake_clock, smtp_factory=factory, extra=("--force-no-dmarc",)) == 0
    values = summary_of(capsys.readouterr().out)
    assert (values["DMARC"], values["SPF"], values["forced no DMARC"]) == ("present (p=none)", "includes_ses", "no")
    assert query(s.db, "SELECT forced_no_dmarc FROM runs") == [(0,)]
