"""Sender settings from .env, message building and SMTP outcome classification
(spec 002 plan D12, D13; Gmail sender and prebuilt messages, spec 006 plan D6).
Never stores or prints SMTP response text or credentials."""
from __future__ import annotations

import dataclasses
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import format_datetime, formataddr, make_msgid
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from dotenv import dotenv_values

from b2b import ConfigError
from b2b.campaign import contains_link_or_html
from b2b.emails import normalize_token, validate

if TYPE_CHECKING:
    from b2b.template import RenderedEmail

STOP_KINDS = frozenset({
    "connection_failed",
    "authentication_failed",
    "sender_refused",
    "provider_throttled",
    "identity_not_verified",
    "message_rejected",
    "connection_lost",
    "interrupted",
})


@dataclass(frozen=True)
class SenderSettings:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    sender: str = ""
    from_name: str = ""
    test_recipients: tuple[str, ...] = ()


@dataclass(frozen=True)
class SendOutcome:
    status: str
    error_kind: str | None
    smtp_code: int | None
    message_id: str | None
    stop: bool


def _outcome(status: str, error_kind: str | None, smtp_code: int | None = None,
             message_id: str | None = None) -> SendOutcome:
    return SendOutcome(status, error_kind, smtp_code, message_id, error_kind in STOP_KINDS)


def _valid_address(value: str) -> str | None:
    token = normalize_token(value)
    return token if validate(token) is None else None


def load_sender_settings(env_path: Path, *, require_test_recipients: bool) -> SenderSettings:
    env_path = Path(env_path)
    if not env_path.is_file():
        raise ConfigError(f"{env_path}: file not found")
    values = dotenv_values(env_path)

    def required(key: str) -> str:
        value = values.get(key) or ""
        if not value.strip():
            raise ConfigError(f"{env_path}: missing {key}")
        return value

    host = required("HOST_EMAIL").strip()
    port_text = required("PORT_EMAIL").strip()
    if port_text not in ("465", "587"):
        raise ConfigError(f"{env_path}: invalid PORT_EMAIL")
    user = required("USER_EMAIL").strip()
    password = required("PASS_EMAIL")
    sender = _valid_address(required("SENDER_EMAIL"))
    if sender is None:
        raise ConfigError(f"{env_path}: invalid SENDER_EMAIL")
    from_name = required("SMTP_FROM_NAME").strip()
    if contains_link_or_html(from_name):
        raise ConfigError(f"{env_path}: invalid SMTP_FROM_NAME")

    test_recipients = _test_recipients(env_path, required, require_test_recipients)
    return SenderSettings(host, int(port_text), user, password, sender, from_name, test_recipients)


def _test_recipients(env_path: Path, required: Callable[[str], str], require: bool) -> tuple[str, ...]:
    if not require:
        return ()
    raw = required("TEST_RECIPIENTS")
    parts = [part for part in raw.split(",") if part.strip()]
    normalized = [_valid_address(part) for part in parts]
    if not 1 <= len(parts) <= 5 or any(address is None for address in normalized):
        raise ConfigError(f"{env_path}: invalid TEST_RECIPIENTS")
    return tuple(normalized)


GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 465


def load_gmail_settings(env_path: Path, *, require_test_recipients: bool) -> SenderSettings:
    """Artemisa campaign sender (spec 006 D6): a Gmail account with an app password; sender = user."""
    env_path = Path(env_path)
    if not env_path.is_file():
        raise ConfigError(f"{env_path}: file not found")
    values = dotenv_values(env_path)

    def required(key: str) -> str:
        value = values.get(key) or ""
        if not value.strip():
            raise ConfigError(f"{env_path}: missing {key}")
        return value

    user = _valid_address(required("ARTEMISA_GMAIL_USER"))
    if user is None:
        raise ConfigError(f"{env_path}: invalid ARTEMISA_GMAIL_USER")
    password = required("ARTEMISA_GMAIL_PASS")
    from_name = required("ARTEMISA_GMAIL_FROM_NAME").strip()
    if contains_link_or_html(from_name):
        raise ConfigError(f"{env_path}: invalid ARTEMISA_GMAIL_FROM_NAME")
    test_recipients = _test_recipients(env_path, required, require_test_recipients)
    return SenderSettings(GMAIL_HOST, GMAIL_PORT, user, password, user, from_name, test_recipients)


def load_artemisa_ses_settings(env_path: Path, *, require_test_recipients: bool) -> SenderSettings:
    """Artemisa campaign through SES (spec 006 D6, `--sender ses`): the SES keys (HOST_EMAIL, PORT_EMAIL,
    USER_EMAIL, PASS_EMAIL, SENDER_EMAIL) with ARTEMISA_GMAIL_FROM_NAME as display name when set."""
    settings = load_sender_settings(env_path, require_test_recipients=require_test_recipients)
    from_name = (dotenv_values(Path(env_path)).get("ARTEMISA_GMAIL_FROM_NAME") or "").strip()
    if from_name:
        if contains_link_or_html(from_name):
            raise ConfigError(f"{env_path}: invalid ARTEMISA_GMAIL_FROM_NAME")
        settings = dataclasses.replace(settings, from_name=from_name)
    return settings


def default_smtp_factory(settings: SenderSettings) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if settings.port == 465:
        return smtplib.SMTP_SSL(settings.host, settings.port, timeout=30, context=context)
    if settings.port == 587:
        client = smtplib.SMTP(settings.host, settings.port, timeout=30)
        client.starttls(context=context)
        return client
    raise ConfigError(f"unsupported SMTP port {settings.port}")


def build_message(settings: SenderSettings, email: RenderedEmail, now: datetime) -> EmailMessage:
    message = EmailMessage(policy=SMTP_POLICY)
    message["From"] = formataddr((settings.from_name, settings.sender))
    message["To"] = email.to
    message["Reply-To"] = settings.sender
    message["Subject"] = email.subject
    message["Date"] = format_datetime(now)
    message["Message-ID"] = make_msgid(domain=settings.sender.rsplit("@", 1)[1])
    message.set_content(email.body, subtype="plain", charset="utf-8", cte="quoted-printable")
    return message


def _quit(client) -> None:
    try:
        client.quit()
    except Exception:
        pass


def check_login(settings: SenderSettings, smtp_factory: Callable | None = None) -> str | None:
    """Connect, log in and quit. Returns None when the login works, else the error kind."""
    factory = smtp_factory or default_smtp_factory
    try:
        client = factory(settings)
    except OSError:
        return "connection_failed"
    try:
        client.login(settings.user, settings.password)
    except smtplib.SMTPAuthenticationError:
        return "authentication_failed"
    except OSError:
        return "connection_failed"
    finally:
        _quit(client)
    return None


def _recipient_code(error: smtplib.SMTPRecipientsRefused) -> int | None:
    for code, _text in error.recipients.values():
        return code
    return None


# Gmail may report its account sending limit at the recipient stage ("550 5.4.5 Daily user sending
# limit exceeded"); that is throttling of the sender, never a bad recipient (spec 006 D6).
_SENDING_LIMIT_MARKERS = (b"5.4.5", b"sending limit")


def _is_sending_limit(text: object) -> bool:
    raw = text if isinstance(text, bytes) else str(text).encode()
    return any(marker in raw.lower() for marker in _SENDING_LIMIT_MARKERS)


def _recipient_outcome(code: int | None, text: object) -> SendOutcome:
    if code is not None and 500 <= code < 600:
        if _is_sending_limit(text):
            return _outcome("temporary_failure", "provider_throttled", code)
        return _outcome("permanent_rejection", "recipient_refused", code)
    return _outcome("temporary_failure", "recipient_deferred", code)


def send_email(settings: SenderSettings, email: RenderedEmail, now: datetime,
               smtp_factory: Callable | None = None) -> SendOutcome:
    return send_message(settings, build_message(settings, email, now), email.to, smtp_factory)


def send_message(settings: SenderSettings, message: EmailMessage, to: str,
                 smtp_factory: Callable | None = None) -> SendOutcome:
    """Send one prebuilt message to one recipient and classify the SMTP outcome."""
    factory = smtp_factory or default_smtp_factory
    try:
        client = factory(settings)
    except OSError:  # includes smtplib.SMTPException subclasses raised while connecting
        return _outcome("temporary_failure", "connection_failed")
    try:
        try:
            client.login(settings.user, settings.password)
        except smtplib.SMTPAuthenticationError as error:
            return _outcome("temporary_failure", "authentication_failed", error.smtp_code)
        except OSError:
            return _outcome("temporary_failure", "connection_failed")

        # Nothing before this call can have delivered the email; anything uncertain after it
        # is classified as unknown and never retried.
        try:
            refused = client.sendmail(settings.sender, [to], message.as_bytes())
        except smtplib.SMTPRecipientsRefused as error:
            for code, text in error.recipients.values():
                return _recipient_outcome(code, text)
            return _recipient_outcome(None, b"")
        except smtplib.SMTPSenderRefused as error:
            return _outcome("temporary_failure", "sender_refused", error.smtp_code)
        except smtplib.SMTPDataError as error:
            code = error.smtp_code
            text = error.smtp_error if isinstance(error.smtp_error, bytes) else str(error.smtp_error).encode()
            if code == 454:
                return _outcome("temporary_failure", "provider_throttled", code)
            if code == 554 and b"not verified" in text.lower():
                return _outcome("temporary_failure", "identity_not_verified", code)
            if 500 <= code < 600:
                return _outcome("temporary_failure", "message_rejected", code)
            return _outcome("temporary_failure", "data_deferred", code)
        except smtplib.SMTPHeloError as error:
            return _outcome("temporary_failure", "connection_failed", error.smtp_code)
        except OSError:  # SMTPServerDisconnected, TimeoutError, other socket errors
            return _outcome("unknown", "connection_lost")

        if refused:
            code, text = next(iter(refused.values()))
            return _recipient_outcome(code, text)
        return _outcome("accepted", None, 250, str(message["Message-ID"]))
    finally:
        _quit(client)
