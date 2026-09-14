"""Tests for sender settings, message building and SMTP outcomes (spec 002 plan D12, D13)."""
import smtplib
from datetime import datetime, timezone
from email import message_from_bytes
from email.policy import default as default_policy

import pytest

from b2b import ConfigError
from b2b.mailer import (
    STOP_KINDS,
    SenderSettings,
    build_message,
    check_login,
    load_sender_settings,
    send_email,
)
from b2b.template import RenderedEmail

NOW = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
EMAIL = RenderedEmail(
    contact_id=7,
    to="ana.perez@example.org",
    subject="Pregunta rápida sobre la nómina de Empresa Ejemplo, C.A.",
    body="Hola Ana,\n\n¿Le interesa? Con responder \"sí\" es suficiente.\n\nP. D.: responda \"no\".\n",
)


def settings(send_env, **overrides):
    return load_sender_settings(send_env(**overrides), require_test_recipients=True)


# --- settings ---------------------------------------------------------------------------------


def test_load_settings(send_env):
    s = settings(send_env)
    assert (s.host, s.port, s.user, s.sender, s.from_name) == (
        "smtp.example.com", 465, "usuario-prueba", "remitente@example.com", "Ana Remitente")
    assert s.password == "clave-de-prueba"
    assert s.test_recipients == ("prueba1@example.org", "prueba2@example.net")
    assert "clave-de-prueba" not in repr(s)


def test_test_recipients_optional_when_not_required(send_env):
    s = load_sender_settings(send_env(TEST_RECIPIENTS=None), require_test_recipients=False)
    assert s.test_recipients == ()


@pytest.mark.parametrize("key", ["HOST_EMAIL", "PORT_EMAIL", "USER_EMAIL", "PASS_EMAIL", "SENDER_EMAIL",
                                 "SMTP_FROM_NAME", "TEST_RECIPIENTS"])
def test_missing_key(send_env, key):
    path = send_env(**{key: None})
    with pytest.raises(ConfigError) as excinfo:
        load_sender_settings(path, require_test_recipients=True)
    assert str(excinfo.value) == f"{path}: missing {key}"


@pytest.mark.parametrize("overrides, key", [
    ({"PORT_EMAIL": "25"}, "PORT_EMAIL"),
    ({"SENDER_EMAIL": "no-es-correo"}, "SENDER_EMAIL"),
    ({"SMTP_FROM_NAME": "Ana www.ejemplo"}, "SMTP_FROM_NAME"),
    ({"TEST_RECIPIENTS": "a@example.org,mal"}, "TEST_RECIPIENTS"),
    ({"TEST_RECIPIENTS": ",".join(f"p{i}@example.org" for i in range(6))}, "TEST_RECIPIENTS"),
])
def test_invalid_key(send_env, overrides, key):
    path = send_env(**overrides)
    with pytest.raises(ConfigError) as excinfo:
        load_sender_settings(path, require_test_recipients=True)
    assert str(excinfo.value) == f"{path}: invalid {key}"


def test_missing_env_file(tmp_path):
    with pytest.raises(ConfigError, match="file not found"):
        load_sender_settings(tmp_path / ".env", require_test_recipients=False)


def test_error_messages_never_contain_secret(send_env):
    path = send_env(PORT_EMAIL="99")
    with pytest.raises(ConfigError) as excinfo:
        load_sender_settings(path, require_test_recipients=True)
    assert "clave-de-prueba" not in str(excinfo.value)


# --- message ----------------------------------------------------------------------------------


def test_build_message_headers_and_body(send_env):
    s = settings(send_env, SMTP_FROM_NAME="José Remitente")
    message = build_message(s, EMAIL, NOW)
    parsed = message_from_bytes(message.as_bytes(), policy=default_policy)
    assert parsed["From"].addresses[0].display_name == "José Remitente"
    assert parsed["From"].addresses[0].addr_spec == "remitente@example.com"
    assert str(parsed["To"]) == "ana.perez@example.org"
    assert str(parsed["Reply-To"]) == "remitente@example.com"
    assert str(parsed["Subject"]) == EMAIL.subject
    assert parsed["Date"].datetime == NOW
    assert str(parsed["Message-ID"]).endswith("@example.com>")
    assert not parsed.is_multipart()
    assert parsed.get_content_type() == "text/plain"
    assert parsed.get_content_charset() == "utf-8"
    assert parsed["Content-Transfer-Encoding"] == "quoted-printable"
    # The SMTP policy writes CRLF line endings on the wire; content is otherwise identical.
    assert parsed.get_content().replace("\r\n", "\n") == EMAIL.body
    assert sorted(k.lower() for k in parsed.keys()) == sorted(
        ["from", "to", "reply-to", "subject", "date", "message-id", "content-type",
         "content-transfer-encoding", "mime-version"])


# --- sending ----------------------------------------------------------------------------------


def outcome_for(send_env, fake_smtp, item):
    factory, log = fake_smtp([item])
    return send_email(settings(send_env), EMAIL, NOW, smtp_factory=factory), log


def test_accepted(send_env, fake_smtp):
    outcome, log = outcome_for(send_env, fake_smtp, None)
    assert (outcome.status, outcome.error_kind, outcome.stop) == ("accepted", None, False)
    raw = log.messages[0][2]
    assert outcome.message_id == str(message_from_bytes(raw, policy=default_policy)["Message-ID"])
    assert log.messages[0][0] == "remitente@example.com"
    assert log.messages[0][1] == ["ana.perez@example.org"]
    assert (log.connects, log.logins, log.quits) == (1, 1, 1)


@pytest.mark.parametrize("error, status, kind, stop", [
    (smtplib.SMTPRecipientsRefused({"ana.perez@example.org": (550, b"no such user")}),
     "permanent_rejection", "recipient_refused", False),
    (smtplib.SMTPRecipientsRefused({"ana.perez@example.org": (450, b"try later")}),
     "temporary_failure", "recipient_deferred", False),
    (smtplib.SMTPSenderRefused(553, b"sender rejected", "remitente@example.com"),
     "temporary_failure", "sender_refused", True),
    (smtplib.SMTPDataError(454, b"Throttling failure: Maximum sending rate exceeded."),
     "temporary_failure", "provider_throttled", True),
    (smtplib.SMTPDataError(554, b"Message rejected: Email address is not verified."),
     "temporary_failure", "identity_not_verified", True),
    (smtplib.SMTPDataError(554, b"Message rejected: content"),
     "temporary_failure", "message_rejected", True),
    (smtplib.SMTPDataError(451, b"local error"),
     "temporary_failure", "data_deferred", False),
    (smtplib.SMTPServerDisconnected("gone"), "unknown", "connection_lost", True),
    (TimeoutError("timed out"), "unknown", "connection_lost", True),
])
def test_sendmail_outcomes(send_env, fake_smtp, error, status, kind, stop):
    outcome, log = outcome_for(send_env, fake_smtp, error)
    assert (outcome.status, outcome.error_kind, outcome.stop) == (status, kind, stop)
    assert outcome.message_id is None
    assert log.quits == 1


def test_refused_dict_return_is_classified(send_env, fake_smtp):
    outcome, _ = outcome_for(send_env, fake_smtp, {"ana.perez@example.org": (550, b"no")})
    assert (outcome.status, outcome.error_kind) == ("permanent_rejection", "recipient_refused")


def test_login_failure(send_env, fake_smtp):
    factory, log = fake_smtp()
    log.login_error = smtplib.SMTPAuthenticationError(535, b"Authentication Credentials Invalid")
    outcome = send_email(settings(send_env), EMAIL, NOW, smtp_factory=factory)
    assert (outcome.status, outcome.error_kind, outcome.stop, outcome.smtp_code) == (
        "temporary_failure", "authentication_failed", True, 535)
    assert log.messages == []


def test_connection_failure(send_env):
    def factory(_settings):
        raise ConnectionRefusedError("refused")

    outcome = send_email(settings(send_env), EMAIL, NOW, smtp_factory=factory)
    assert (outcome.status, outcome.error_kind, outcome.stop) == ("temporary_failure", "connection_failed", True)


def test_quit_errors_ignored(send_env, fake_smtp, monkeypatch):
    factory, log = fake_smtp()

    def failing_factory(s):
        client = factory(s)
        client.quit = lambda: (_ for _ in ()).throw(smtplib.SMTPServerDisconnected("closed"))
        return client

    outcome = send_email(settings(send_env), EMAIL, NOW, smtp_factory=failing_factory)
    assert outcome.status == "accepted"


def test_check_login(send_env, fake_smtp):
    factory, log = fake_smtp()
    assert check_login(settings(send_env), smtp_factory=factory) is None
    log.login_error = smtplib.SMTPAuthenticationError(535, b"bad")
    assert check_login(settings(send_env), smtp_factory=factory) == "authentication_failed"

    def refusing(_settings):
        raise OSError("unreachable")

    assert check_login(settings(send_env), smtp_factory=refusing) == "connection_failed"


def test_stop_kinds():
    assert "connection_lost" in STOP_KINDS and "recipient_deferred" not in STOP_KINDS
