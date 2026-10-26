"""Spec 006 US1–US3: import, preview, test and send of the Artemisa announcement (fakes only)."""
from __future__ import annotations

import random
import re
import smtplib
import sqlite3
from datetime import timedelta
from email import message_from_bytes
from email.policy import default as default_policy
from types import SimpleNamespace

import pytest

from b2b import store
from b2b.send_artemisa import main

CAMPAIGN = "artemisa-fundadores-2026"
HEADER = "user_id,email,first_name,last_name,kyc_full_name,nickname,phone,status_kyc,paypal_offers,types,first_offer,last_offer\n"
ROWS = [
    "1,ana@example.com,ANA,X,X,anita,'+1 0000000001,Verificado,1,SELL,,\n",
    "2,luis@example.org,LUIS,X,X,,'+1 0000000002,Verificado,0,\"BUY,SELL\",,\n",
    "3,sara@example.net,SARA,X,X,,04120000000,Verificado,0,SELL,,\n",
    "4,jose@example.com,JOSÉ,X,X,,'+1 0000000004,Verificado,0,SELL,,\n",
]


def forbidden_smtp(settings):
    raise AssertionError("SMTP must not be used in this mode")


@pytest.fixture
def setup(tmp_path, artemisa_env, artemisa_files, db_path):
    def make(rows=ROWS, env=None, **overrides):
        csv_path = tmp_path / "artemisa.csv"
        csv_path.write_text("﻿" + HEADER + "".join(rows), encoding="utf-8")
        return SimpleNamespace(csv=csv_path, env=artemisa_env(**(env or {})), config=artemisa_files(**overrides),
                               db=db_path, previews=tmp_path / "previews")

    return make


def run(s, mode, clock, smtp_factory=forbidden_smtp, answer=CAMPAIGN, extra=()):
    argv = ["--mode", mode, "--csv", str(s.csv), "--config", str(s.config), "--db", str(s.db), "--env", str(s.env),
            "--previews-dir", str(s.previews), *extra]
    return main(argv, smtp_factory=smtp_factory, now=clock.now, sleep=clock.sleep, ask=lambda _p: answer,
                rng=random.Random(0))


def query(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def summary_of(text):
    values = {}
    for line in text.splitlines():
        if line.startswith("send_artemisa: "):
            values["_result"] = line.split(" ", 1)[1]
        match = re.match(r"^  ([^:]+):\s+(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def messages(log):
    return [message_from_bytes(msg, policy=default_policy) for _f, _t, msg in log.messages]


def recipients(log):
    return [to[0] for _f, to, _m in log.messages]


# --- import -----------------------------------------------------------------------------------


def test_import_creates_tracker_and_is_repeatable(setup, fake_clock, capsys):
    s = setup()
    assert run(s, "import", fake_clock) == 0
    values = summary_of(capsys.readouterr().out)
    assert (values["rows read"], values["new contacts"], values["contacts in database"]) == ("4", "4", "4")
    assert query(s.db, "SELECT user_id, email, first_name FROM contacts ORDER BY id") == [
        (1, "ana@example.com", "ANA"), (2, "luis@example.org", "LUIS"), (3, "sara@example.net", "SARA"),
        (4, "jose@example.com", "JOSÉ")]
    conn = sqlite3.connect(s.db)
    conn.execute("UPDATE contacts SET times_contacted = 1, last_contacted_at = 'x', opted_out = 1, opted_out_at = 'x' WHERE id = 1")
    conn.commit()
    conn.close()
    assert run(s, "import", fake_clock) == 0
    values = summary_of(capsys.readouterr().out)
    assert (values["new contacts"], values["unchanged contacts"]) == ("0", "4")
    assert query(s.db, "SELECT times_contacted, opted_out FROM contacts WHERE id = 1") == [(1, 1)]


def test_import_errors(setup, fake_clock, tmp_path, capsys):
    s = setup()
    s.csv = tmp_path / "missing.csv"
    assert run(s, "import", fake_clock) == 1
    assert "cannot read file" in capsys.readouterr().err
    s = setup(rows=[])
    s.csv.write_text("user_id,email\n", encoding="utf-8")
    assert run(s, "import", fake_clock) == 1
    assert "missing header" in capsys.readouterr().err


def test_import_refuses_b2b_database(setup, fake_clock, capsys):
    s = setup()
    conn = store.connect(s.db)
    store.ensure_schema(conn)
    conn.close()
    assert run(s, "import", fake_clock) == 2
    assert "not an Artemisa database" in capsys.readouterr().err


# --- preview and test ----------------------------------------------------------------------------


def test_preview_writes_plain_emails(setup, fake_clock, capsys):
    s = setup()
    assert run(s, "import", fake_clock) == 0
    assert run(s, "preview", fake_clock) == 0
    values = summary_of(capsys.readouterr().out)
    assert (values["_result"], values["eligible contacts"], values["previewed"]) == ("preview done", "4", "4")
    files = list(s.previews.glob("artemisa-fundadores-2026-*.txt"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Emails: 4" in text and "To: ana@example.com" in text and "Hola Ana," in text and "Hola José," in text
    assert "Subject: Sé fundador en Artemisa P2P" in text and "@artemisa_p2p_bot" in text
    assert "<" not in text.replace("<subject>", "") and text.count("responde \"no\"") == 4
    assert query(s.db, "SELECT COUNT(*) FROM send_attempts") == [(0,)]


def test_preview_needs_database(setup, fake_clock, capsys):
    s = setup()
    assert run(s, "preview", fake_clock) == 2
    assert "database not found" in capsys.readouterr().err


def test_test_mode_sends_multipart_with_inline_images(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    assert run(s, "test", fake_clock, factory) == 0
    assert recipients(log) == ["prueba1@example.org", "prueba2@example.net"]
    assert summary_of(capsys.readouterr().out)["test emails sent"] == "2"
    msg = messages(log)[0]
    assert msg["Subject"] == "[PRUEBA] Sé fundador en Artemisa P2P: monta tu oferta y opera sin custodia"
    assert msg["From"] == "Artemisa P2P <artemisa-prueba@example.com>"
    assert msg.get_content_type() == "multipart/alternative"
    plain, related = msg.get_payload()
    assert plain.get_content_type() == "text/plain" and "Hola Ana," in plain.get_content()
    assert related.get_content_type() == "multipart/related"
    html_part, *images = related.get_payload()
    assert html_part.get_content_type() == "text/html"
    html = html_part.get_content()
    assert "Hola Ana," in html and "<script" not in html and "http" not in html
    assert [i.get_content_type() for i in images] == ["image/png", "image/png"]
    assert [i.get_filename() for i in images] == ["27.png", "43.png"]
    for image in images:
        assert f'cid:{image["Content-ID"].strip("<>")}' in html
        assert image.get_content().startswith(b"\x89PNG")
    assert log.messages[0][2].count(b"Content-Type: image/png") == 2
    assert s.db.exists() is False


def test_sender_ses_uses_ses_keys_with_artemisa_name(setup, fake_clock, fake_smtp, send_env, capsys):
    s = setup()
    s.env = send_env(ARTEMISA_GMAIL_FROM_NAME="Artemisa P2P")
    factory, log = fake_smtp()
    assert run(s, "test", fake_clock, factory, extra=["--sender", "ses"]) == 0
    msg = messages(log)[0]
    assert msg["From"] == "Artemisa P2P <remitente@example.com>" and msg["Reply-To"] == "remitente@example.com"
    assert log.messages[0][0] == "remitente@example.com" and msg.get_content_type() == "multipart/alternative"
    assert run(s, "import", fake_clock) == 0
    factory2, log2 = fake_smtp()
    assert send(s, fake_clock, factory2, "--sender", "ses") == 0
    assert len(log2.messages) == 4 and "sender:          ses" in capsys.readouterr().out
    s.env = send_env()  # no Artemisa name: the SES display name is used
    factory3, log3 = fake_smtp()
    assert run(s, "test", fake_clock, factory3, extra=["--sender", "ses"]) == 0
    assert messages(log3)[0]["From"] == "Ana Remitente <remitente@example.com>"


def test_test_mode_stops_on_failure(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp([smtplib.SMTPDataError(550, b"5.4.5 Daily user sending limit exceeded")])
    assert run(s, "test", fake_clock, factory) == 4
    assert summary_of(capsys.readouterr().out)["stop reason"] == "message_rejected"


@pytest.mark.parametrize("key", ["ARTEMISA_GMAIL_USER", "ARTEMISA_GMAIL_PASS", "ARTEMISA_GMAIL_FROM_NAME", "TEST_RECIPIENTS"])
def test_missing_gmail_keys(setup, fake_clock, key, capsys):
    s = setup(env={key: None})
    assert run(s, "test", fake_clock) == 1
    assert f"missing {key}" in capsys.readouterr().err


def test_send_only_flags(setup, fake_clock, capsys):
    s = setup()
    assert run(s, "preview", fake_clock, extra=["--confirm", CAMPAIGN]) == 1
    assert "--confirm is only allowed with --mode send" in capsys.readouterr().err


# --- send -------------------------------------------------------------------------------------


def send(s, clock, factory, *extra, answer=CAMPAIGN):
    return run(s, "send", clock, factory, answer=answer, extra=extra)


def test_send_everyone_under_hourly_cap_then_nothing(setup, fake_clock, fake_smtp, capsys):
    s = setup(hourly_cap="2")
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp()
    started = fake_clock.now()
    assert send(s, fake_clock, factory, "--wait-for-window") == 0
    out = capsys.readouterr().out
    assert recipients(log) == ["ana@example.com", "luis@example.org", "sara@example.net", "jose@example.com"]
    assert log.logins == 5  # login check + 4 emails
    assert fake_clock.now() - started >= timedelta(hours=1)
    assert "campaign:        artemisa-fundadores-2026" in out and "recipients:      4" in out
    values = summary_of(out)
    assert (values["_result"], values["accepted"], values["stop reason"]) == ("send done", "4", "all_sent")
    assert query(s.db, "SELECT stop_reason FROM runs") == [("all_sent",)]
    assert query(s.db, "SELECT COUNT(*) FROM send_attempts WHERE status = 'accepted' AND campaign = ?", (CAMPAIGN,)) == [(4,)]
    assert query(s.db, "SELECT COUNT(*) FROM contacts WHERE times_contacted = 1") == [(4,)]
    msg = messages(log)[3]
    assert "Hola José," in msg.get_payload()[0].get_content()
    factory2, log2 = fake_smtp()
    assert send(s, fake_clock, factory2) == 0
    assert log2.messages == [] and summary_of(capsys.readouterr().out)["_result"] == "send nothing_to_send"


def test_daily_cap_stops_or_waits(setup, fake_clock, fake_smtp, capsys):
    s = setup(daily_cap="3")
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp()
    assert send(s, fake_clock, factory) == 4
    assert len(log.messages) == 3
    assert summary_of(capsys.readouterr().out)["stop reason"] == "daily_cap"
    assert query(s.db, "SELECT stop_reason FROM runs") == [("daily_cap",)]
    started = fake_clock.now()
    factory2, log2 = fake_smtp()
    assert send(s, fake_clock, factory2, "--wait-for-window") == 0
    assert recipients(log2) == ["jose@example.com"]
    assert fake_clock.now() - started >= timedelta(hours=23)
    assert "daily cap reached; waiting until" in capsys.readouterr().out


def test_outside_window(setup, fake_clock, fake_smtp, capsys):
    s = setup(send_start='"10:00"')  # clock is 09:00 Caracas
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp()
    assert send(s, fake_clock, factory) == 0
    values = summary_of(capsys.readouterr().out)
    assert (values["_result"], values["next window opens"]) == ("send outside_window", "2026-09-14 10:00 America/Caracas")
    assert log.messages == []
    assert send(s, fake_clock, factory, "--wait-for-window") == 0
    assert len(log.messages) == 4 and "waiting for the send window" in capsys.readouterr().out


def test_window_closes_mid_run(setup, fake_clock, fake_smtp, capsys):
    s = setup(hourly_cap="1", send_end='"09:30"')
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp()
    assert send(s, fake_clock, factory) == 4
    assert len(log.messages) == 1 and summary_of(capsys.readouterr().out)["stop reason"] == "window_closed"


def test_confirmation_mismatch(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp()
    assert send(s, fake_clock, factory, answer="otra") == 3
    assert log.messages == [] and "does not match" in capsys.readouterr().err
    assert query(s.db, "SELECT COUNT(*) FROM runs") == [(0,)]
    assert send(s, fake_clock, factory, "--confirm", CAMPAIGN) == 0
    assert len(log.messages) == 4


def test_login_failure_refuses(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp()
    log.login_error = smtplib.SMTPAuthenticationError(535, b"bad")
    assert send(s, fake_clock, factory) == 1
    assert "SMTP login check failed (authentication_failed)" in capsys.readouterr().err
    assert log.messages == []


def test_pending_attempt_recovered_never_resent(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    assert run(s, "import", fake_clock) == 0
    conn = sqlite3.connect(s.db)
    run_id = conn.execute("INSERT INTO runs (kind, campaign, step, started_at) VALUES ('send_production', ?, 1, 'x')",
                          (CAMPAIGN,)).lastrowid
    conn.execute("INSERT INTO send_attempts (run_id, contact_id, campaign, step, status, created_at) "
                 "VALUES (?, 2, ?, 1, 'pending', '2026-09-14T12:00:00Z')", (run_id, CAMPAIGN))
    conn.commit()
    conn.close()
    factory, log = fake_smtp()
    assert send(s, fake_clock, factory) == 0
    assert recipients(log) == ["ana@example.com", "sara@example.net", "jose@example.com"]
    assert query(s.db, "SELECT status, error_kind FROM send_attempts WHERE contact_id = 2") == [("unknown", "interrupted")]


def test_permanent_rejection_marks_bounced_and_stop_kinds(setup, fake_clock, fake_smtp, capsys):
    s = setup(bounce_min_sends="2", bounce_pause_threshold="0.1")
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp([{"ana@example.com": (550, b"no such user")}, {}, {}, {}])
    assert send(s, fake_clock, factory) == 4
    values = summary_of(capsys.readouterr().out)
    assert (values["permanent rejections"], values["accepted"], values["stop reason"]) == ("1", "1", "bounce_threshold")
    assert query(s.db, "SELECT bounced FROM contacts WHERE id = 1") == [(1,)]
    factory2, log2 = fake_smtp()
    assert send(s, fake_clock, factory2) == 3  # stays paused
    assert "rejection rate is above the pause threshold" in capsys.readouterr().err

    s2 = setup()
    s2.db = s.db.parent / "two.sqlite3"
    assert run(s2, "import", fake_clock) == 0
    factory3, log3 = fake_smtp([{}, smtplib.SMTPDataError(454, b"4.7.0 Too many login attempts")])
    assert send(s2, fake_clock, factory3) == 4
    assert summary_of(capsys.readouterr().out)["stop reason"] == "provider_throttled"
    assert query(s2.db, "SELECT contact_id, status FROM send_attempts ORDER BY id") == [(1, "accepted"), (2, "temporary_failure")]


def test_temporary_failure_limit(setup, fake_clock, fake_smtp, capsys):
    s = setup(temporary_failure_limit="2")
    assert run(s, "import", fake_clock) == 0
    deferred = {"x": (451, b"try later")}
    factory, log = fake_smtp([{"ana@example.com": (451, b"later")}, {"luis@example.org": (451, b"later")}, {}])
    assert send(s, fake_clock, factory) == 4
    assert summary_of(capsys.readouterr().out)["stop reason"] == "temporary_failures"
    assert len(log.messages) == 2


def test_notify_sends_summary_after_run(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp()
    assert send(s, fake_clock, factory, "--notify") == 0
    assert recipients(log)[-2:] == ["prueba1@example.org", "prueba2@example.net"]
    notice = messages(log)[-1]
    assert notice["Subject"] == "[artemisa] artemisa-fundadores-2026: done (all_sent)"
    assert "accepted:" in notice.get_content() and "example.com" not in notice.get_content()


def test_lock_refuses_second_run(setup, fake_clock, fake_smtp, capsys):
    from b2b import tracking

    s = setup()
    assert run(s, "import", fake_clock) == 0
    factory, log = fake_smtp()
    with tracking.send_lock(s.db):
        assert send(s, fake_clock, factory) == 3
    assert "another send run is active" in capsys.readouterr().err


def test_gmail_sending_limit_at_recipient_stage_is_throttling(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    assert run(s, "import", fake_clock) == 0
    limit = {"ana@example.com": (550, b"5.4.5 Daily user sending limit exceeded. For more information")}
    factory, log = fake_smtp([{}, smtplib.SMTPRecipientsRefused(limit)])
    assert send(s, fake_clock, factory) == 4
    values = summary_of(capsys.readouterr().out)
    assert (values["stop reason"], values["accepted"], values["permanent rejections"]) == ("provider_throttled", "1", "0")
    assert query(s.db, "SELECT COUNT(*) FROM contacts WHERE bounced = 1") == [(0,)]
    assert query(s.db, "SELECT status, error_kind FROM send_attempts WHERE contact_id = 2") == [("temporary_failure", "provider_throttled")]
