"""Artemisa P2P founders campaign: import the users CSV, preview, test and send the announcement
from the Artemisa Gmail account (spec 006 plan D7, D8).

Usage: python -m b2b.send_artemisa [--mode import|preview|test|send] — prints counts only; never
prints contact values, credentials or SMTP response text.
"""
from __future__ import annotations

import argparse
import dataclasses
import html
import random
import signal
import sqlite3
import sys
import threading
import time as time_module
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import format_datetime, formataddr, make_msgid
from pathlib import Path
from typing import Callable, Sequence

from b2b import ConfigError, InputError, artemisa_store, pacing, tracking
from b2b.artemisa_config import ArtemisaCampaign, load_artemisa_campaign, load_artemisa_template, render_artemisa
from b2b.artemisa_csv import read_artemisa_csv
from b2b.mailer import (SenderSettings, SendOutcome, check_login, load_artemisa_ses_settings, load_gmail_settings,
                        send_email, send_message)
from b2b.preview import write_preview
from b2b.template import RenderedEmail, Template

PROG = "send_artemisa"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_DATABASE = 2
EXIT_REFUSED = 3
EXIT_STOPPED = 4
EXIT_INTERRUPTED = 130

_WEEK = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_SEND_ONLY_OPTIONS = ("confirm", "wait_for_window", "notify")
_IMAGE_SUBTYPES = {".png": "png"}

Image = tuple[str, bytes]


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise _ArgumentError(message)


@dataclass
class _Context:
    args: argparse.Namespace
    smtp_factory: Callable | None
    now: Callable[[], datetime]
    sleep: Callable[[float], None]
    ask: Callable[[str], str]
    rng: random.Random


@dataclass
class Summary:
    mode: str
    result: str
    campaign: str
    eligible: int = 0
    selected: int = 0
    previewed: int = 0
    test_sent: int = 0
    accepted: int = 0
    permanent_rejections: int = 0
    temporary_failures: int = 0
    unknown: int = 0
    rejected: int = 0
    rejection_base: int = 0
    stop_reason: str = "-"
    next_window: str = "-"
    preview_path: str = "-"


def format_summary(summary: Summary) -> str:
    rate = (summary.rejected / summary.rejection_base * 100) if summary.rejection_base else 0
    rows = [
        ("eligible contacts:", summary.eligible),
        ("selected:", summary.selected),
        ("previewed:", summary.previewed),
        ("test emails sent:", summary.test_sent),
        ("accepted:", summary.accepted),
        ("permanent rejections:", summary.permanent_rejections),
        ("temporary failures:", summary.temporary_failures),
        ("unknown outcome:", summary.unknown),
        ("rejection rate:", f"{rate:.1f}% ({summary.rejected} of {summary.rejection_base})"),
        ("stop reason:", summary.stop_reason),
        ("next window opens:", summary.next_window),
    ]
    lines = [f"{PROG}: {summary.mode} {summary.result}", f"campaign: {summary.campaign}"]
    lines += [f"  {label:<26}{value}" for label, value in rows]
    lines.append(f"preview: {summary.preview_path}")
    return "\n".join(lines) + "\n"


def _error(message: str) -> None:
    print(f"{PROG}: error: {message}", file=sys.stderr)


def _log(message: str) -> None:
    print(f"{PROG}: {message}", flush=True)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(prog=f"python -m b2b.{PROG}",
                     description="Import, preview, test or send the Artemisa P2P announcement.")
    parser.add_argument("--mode", choices=("import", "preview", "test", "send"), default="preview")
    parser.add_argument("--csv", default="contactos/artemisa.csv", help="import mode: the users export")
    parser.add_argument("--config", default="config/artemisa.toml")
    parser.add_argument("--db", default="data/artemisa.sqlite3")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--sender", choices=("gmail", "ses"), default="gmail",
                        help="gmail: ARTEMISA_GMAIL_* keys (default); ses: the SES keys HOST_EMAIL … SENDER_EMAIL")
    parser.add_argument("--previews-dir", default="data/previews")
    parser.add_argument("--confirm", metavar="CAMPAIGN", default=None,
                        help="send mode: confirm the campaign name at launch instead of typing it")
    parser.add_argument("--wait-for-window", action="store_true",
                        help="send mode: sleep until the send window opens or the daily cap frees instead of stopping")
    parser.add_argument("--notify", action="store_true",
                        help="send mode: email the counts-only summary to TEST_RECIPIENTS when the run ends")
    args = parser.parse_args(argv)
    if args.mode != "send":
        for name in _SEND_ONLY_OPTIONS:
            if getattr(args, name) not in (None, False):
                raise _ArgumentError(f"--{name.replace('_', '-')} is only allowed with --mode send")
    return args


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv: list[str] | None = None, *, smtp_factory=None, now=None, sleep=None, ask=None, rng=None) -> int:
    try:
        args = _parse_args(argv)
    except _ArgumentError as exc:
        _error(str(exc))
        return EXIT_CONFIG
    ctx = _Context(args, smtp_factory, now or (lambda: datetime.now(timezone.utc)), sleep or time_module.sleep,
                   ask or input, rng or random.Random())
    previous_handler = None
    if args.mode == "send" and threading.current_thread() is threading.main_thread():
        previous_handler = signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        if args.mode == "import":
            return _import(ctx)
        if args.mode == "preview":
            return _preview(ctx)
        if args.mode == "test":
            return _test_send(ctx)
        return _production(ctx)
    except KeyboardInterrupt:
        _error("interrupted")
        return EXIT_INTERRUPTED
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)


# --- shared ---------------------------------------------------------------------------------


@dataclass
class _Loaded:
    campaign: ArtemisaCampaign
    template: Template
    images: list[Image]
    settings: SenderSettings


def _read_images(campaign: ArtemisaCampaign) -> list[Image]:
    images: list[Image] = []
    for path in campaign.images:
        if path.suffix.lower() not in _IMAGE_SUBTYPES:
            raise ConfigError(f"{path}: only PNG images are supported")
        images.append((path.name, path.read_bytes()))
    return images


def _load(ctx: _Context) -> _Loaded:
    campaign = load_artemisa_campaign(Path(ctx.args.config))
    template = load_artemisa_template(campaign.template, campaign.phrases.opt_out)
    images = _read_images(campaign)
    needs_recipients = ctx.args.mode == "test" or ctx.args.notify
    loader = load_artemisa_ses_settings if ctx.args.sender == "ses" else load_gmail_settings
    settings = loader(Path(ctx.args.env), require_test_recipients=needs_recipients)
    return _Loaded(campaign, template, images, settings)


def _load_or_report(ctx: _Context) -> _Loaded | None:
    try:
        return _load(ctx)
    except ConfigError as exc:
        _error(str(exc))
    except OSError as exc:
        _error(f"{exc.filename}: cannot read file")
    return None


def _open_database(db_path: Path, *, create: bool) -> sqlite3.Connection | None:
    if not create and not db_path.is_file():
        _error(f"{db_path}: database not found (run --mode import first)")
        return None
    try:
        conn = artemisa_store.connect(db_path)
        artemisa_store.ensure_schema(conn)
        return conn
    except artemisa_store.SchemaError as exc:
        _error(str(exc))
    except sqlite3.Error as exc:
        _error(f"{db_path}: database error ({type(exc).__name__})")
    return None


def _render_all(loaded: _Loaded, conn: sqlite3.Connection, summary: Summary) -> list[RenderedEmail]:
    recipients = artemisa_store.select_recipients(conn, loaded.campaign.name)
    emails = [
        render_artemisa(loaded.template, loaded.campaign.phrases, to=r.email, contact_id=r.contact_id,
                        first_name=r.first_name, sender_name=loaded.settings.from_name)
        for r in recipients
    ]
    summary.eligible = len(recipients)
    summary.selected = len(emails)
    return emails


def _html_body(body: str, cids: Sequence[str]) -> str:
    paragraphs = [block for block in body.strip().split("\n\n") if block.strip()]
    parts = ["<p>" + "<br>".join(html.escape(line) for line in block.split("\n")) + "</p>" for block in paragraphs]
    for cid in cids:
        parts.append(f'<p><img src="cid:{cid}" width="540" alt="Artemisa P2P" '
                     'style="max-width:100%;height:auto;display:block;"></p>')
    return ("<!DOCTYPE html><html><body style=\"margin:0;padding:16px;font-family:Arial,Helvetica,sans-serif;"
            "font-size:16px;line-height:1.5;color:#111111;\">" + "".join(parts) + "</body></html>")


def build_artemisa_message(settings: SenderSettings, email: RenderedEmail, images: Sequence[Image],
                           now: datetime) -> EmailMessage:
    """Plain text + HTML alternative with the images inline (spec 006 D7); no external resources."""
    domain = settings.sender.rsplit("@", 1)[1]
    message = EmailMessage(policy=SMTP_POLICY)
    message["From"] = formataddr((settings.from_name, settings.sender))
    message["To"] = email.to
    message["Reply-To"] = settings.sender
    message["Subject"] = email.subject
    message["Date"] = format_datetime(now)
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(email.body, subtype="plain", charset="utf-8", cte="quoted-printable")
    cids = [make_msgid(domain=domain) for _ in images]
    message.add_alternative(_html_body(email.body, [cid.strip("<>") for cid in cids]), subtype="html",
                            charset="utf-8")
    html_part = message.get_payload()[-1]
    for (name, data), cid in zip(images, cids):
        html_part.add_related(data, maintype="image", subtype=_IMAGE_SUBTYPES[Path(name).suffix.lower()],
                              cid=cid, filename=name)
    return message


def _send_one(loaded: _Loaded, email: RenderedEmail, now: datetime, smtp_factory) -> SendOutcome:
    message = build_artemisa_message(loaded.settings, email, loaded.images, now)
    return send_message(loaded.settings, message, email.to, smtp_factory)


def _local_text(campaign: ArtemisaCampaign, moment: datetime) -> str:
    return f"{pacing.local_now(campaign, moment):%Y-%m-%d %H:%M} {campaign.timezone}"


def _print_summary(summary: Summary) -> None:
    print(format_summary(summary), end="", flush=True)


def _count(summary: Summary, outcome: SendOutcome) -> None:
    if outcome.status == "accepted":
        summary.accepted += 1
    elif outcome.status == "permanent_rejection":
        summary.permanent_rejections += 1
    elif outcome.status == "temporary_failure":
        summary.temporary_failures += 1
    else:
        summary.unknown += 1


# --- import ---------------------------------------------------------------------------------


def _import(ctx: _Context) -> int:
    csv_path = Path(ctx.args.csv)
    try:
        result = read_artemisa_csv(csv_path)
    except InputError as exc:
        _error(str(exc))
        return EXIT_CONFIG
    except OSError:
        _error(f"{csv_path}: cannot read file")
        return EXIT_CONFIG
    except (UnicodeDecodeError, ValueError):
        _error(f"{csv_path}: not a UTF-8 CSV file")
        return EXIT_CONFIG
    conn = _open_database(Path(ctx.args.db), create=True)
    if conn is None:
        return EXIT_DATABASE
    try:
        with artemisa_store.transaction(conn):
            upsert = artemisa_store.upsert_contacts(conn, result.rows, _timestamp(ctx.now()))
        total = artemisa_store.count_contacts(conn)
    except sqlite3.Error as exc:
        _error(f"{ctx.args.db}: database error ({type(exc).__name__})")
        return EXIT_DATABASE
    finally:
        conn.close()
    rejected = sum(result.rejected.values())
    rows = [
        ("rows read:", len(result.rows) + rejected),
        ("new contacts:", upsert.new),
        ("updated contacts:", upsert.updated),
        ("unchanged contacts:", upsert.unchanged),
        ("email conflicts:", upsert.conflict),
        ("rejected invalid user id:", result.rejected["invalid_user_id"]),
        ("rejected invalid email:", result.rejected["invalid_email"]),
        ("rejected duplicate user id:", result.rejected["duplicate_user_id"]),
        ("rejected duplicate email:", result.rejected["duplicate_email"]),
        ("contacts in database:", total),
    ]
    print(f"{PROG}: import done")
    for label, value in rows:
        print(f"  {label:<28}{value}")
    return EXIT_OK


# --- preview --------------------------------------------------------------------------------


def _preview(ctx: _Context) -> int:
    loaded = _load_or_report(ctx)
    if loaded is None:
        return EXIT_CONFIG
    conn = _open_database(Path(ctx.args.db), create=False)
    if conn is None:
        return EXIT_DATABASE
    try:
        summary = Summary("preview", "done", loaded.campaign.name)
        emails = _render_all(loaded, conn, summary)
    finally:
        conn.close()
    path = write_preview(Path(ctx.args.previews_dir), loaded.campaign, emails, ctx.now())
    summary.previewed = len(emails)
    summary.preview_path = str(path)
    if not emails:
        summary.result = "nothing_to_send"
    _print_summary(summary)
    return EXIT_OK


# --- test send ------------------------------------------------------------------------------


def _test_send(ctx: _Context) -> int:
    loaded = _load_or_report(ctx)
    if loaded is None:
        return EXIT_CONFIG
    summary = Summary("test", "done", loaded.campaign.name)
    for recipient in loaded.settings.test_recipients:
        email = render_artemisa(loaded.template, loaded.campaign.phrases, to=recipient, contact_id=None,
                                first_name=loaded.campaign.test_sample.nombre, sender_name=loaded.settings.from_name)
        email = dataclasses.replace(email, subject=f"[PRUEBA] {email.subject}")
        outcome = _send_one(loaded, email, ctx.now(), ctx.smtp_factory)
        if outcome.status != "accepted":
            _count(summary, outcome)
            summary.result = "stopped"
            summary.stop_reason = outcome.error_kind or outcome.status
            _error(f"test send stopped ({summary.stop_reason})")
            _print_summary(summary)
            return EXIT_STOPPED
        summary.test_sent += 1
    _print_summary(summary)
    return EXIT_OK


# --- production -----------------------------------------------------------------------------


def _production(ctx: _Context) -> int:
    db_path = Path(ctx.args.db)
    try:
        with tracking.send_lock(db_path):
            return _production_locked(ctx, db_path)
    except tracking.SendLockBusy:
        _error("another send run is active")
        return EXIT_REFUSED


def _window_text(campaign: ArtemisaCampaign) -> str:
    indexes = sorted(_WEEK.index(day) for day in campaign.send_days)
    if len(indexes) > 1 and indexes == list(range(indexes[0], indexes[-1] + 1)):
        day_text = f"{_WEEK[indexes[0]]}–{_WEEK[indexes[-1]]}"
    else:
        day_text = ",".join(_WEEK[i] for i in indexes)
    return f"{day_text} {campaign.send_start:%H:%M}–{campaign.send_end:%H:%M} {campaign.timezone}"


def _wait_for_window(ctx: _Context, campaign: ArtemisaCampaign, moment: datetime) -> None:
    opens = pacing.next_window_start(campaign, moment)
    _log(f"waiting for the send window to open at {_local_text(campaign, opens)}")
    ctx.sleep(max(0.0, (opens - ctx.now()).total_seconds()))


def _notify(ctx: _Context, settings: SenderSettings, summary: Summary) -> None:
    subject = f"[artemisa] {summary.campaign}: {summary.result} ({summary.stop_reason})"
    body = format_summary(summary)
    for recipient in settings.test_recipients:
        notice = RenderedEmail(contact_id=None, to=recipient, subject=subject, body=body)
        outcome = send_email(settings, notice, ctx.now(), ctx.smtp_factory)
        if outcome.status != "accepted":
            _error(f"summary email not sent ({outcome.error_kind or outcome.status})")


def _rejection_exceeded(conn: sqlite3.Connection, campaign: ArtemisaCampaign, summary: Summary) -> bool:
    summary.rejected, summary.rejection_base = tracking.campaign_bounce(conn, campaign.name, 1)
    return tracking.bounce_exceeded(summary.rejected, summary.rejection_base,
                                    campaign.bounce_pause_threshold, campaign.bounce_min_sends)


def _production_locked(ctx: _Context, db_path: Path) -> int:
    loaded = _load_or_report(ctx)
    if loaded is None:
        return EXIT_CONFIG
    campaign, settings = loaded.campaign, loaded.settings
    conn = _open_database(db_path, create=False)
    if conn is None:
        return EXIT_DATABASE
    try:
        summary = Summary("send", "refused", campaign.name)
        tracking.recover_pending(conn, _timestamp(ctx.now()))

        if _rejection_exceeded(conn, campaign, summary):
            summary.stop_reason = "bounce_threshold"
            _error("campaign rejection rate is above the pause threshold; sending stays paused")
            _print_summary(summary)
            return EXIT_REFUSED

        login_error = check_login(settings, ctx.smtp_factory)
        if login_error is not None:
            _error(f"SMTP login check failed ({login_error})")
            return EXIT_CONFIG

        now = ctx.now()
        if not pacing.window_contains(campaign, now):
            if not ctx.args.wait_for_window:
                summary.result = "outside_window"
                summary.next_window = _local_text(campaign, pacing.next_window_start(campaign, now))
                _print_summary(summary)
                return EXIT_OK
            _wait_for_window(ctx, campaign, now)

        emails = _render_all(loaded, conn, summary)
        if not emails:
            summary.result = "nothing_to_send"
            _print_summary(summary)
            return EXIT_OK

        print(f"campaign:        {campaign.name}")
        print(f"sender:          {ctx.args.sender}")
        print(f"recipients:      {len(emails)}")
        print(f"hourly cap:      {campaign.hourly_cap} per hour")
        print(f"daily cap:       {campaign.daily_cap} per 24 hours")
        print(f"send window:     {_window_text(campaign)}")
        print(f"images:          {len(loaded.images)}", flush=True)
        if ctx.args.confirm is not None:
            answer = ctx.args.confirm
            _log("confirmation supplied at launch (--confirm)")
        else:
            answer = ctx.ask("Type the campaign name to start sending: ")
        if (answer or "").strip() != campaign.name:
            _error("confirmation does not match the campaign name; nothing was sent")
            _print_summary(summary)
            return EXIT_REFUSED

        run_id = tracking.start_run(conn, campaign.name, 1, False, _timestamp(ctx.now()))
        try:
            stop_reason = _send_loop(ctx, conn, loaded, emails, run_id, summary)
        except KeyboardInterrupt:
            summary.result = "stopped"
            if ctx.args.notify:
                _notify(ctx, settings, summary)
            raise
        finished = stop_reason == "all_sent"
        summary.result = "done" if finished else "stopped"
        if not finished:
            _error(f"sending stopped ({stop_reason})")
        _print_summary(summary)
        if ctx.args.notify:
            _notify(ctx, settings, summary)
        return EXIT_OK if finished else EXIT_STOPPED
    finally:
        conn.close()


def _pre_send_stop(ctx: _Context, conn: sqlite3.Connection, campaign: ArtemisaCampaign, summary: Summary) -> str | None:
    """Return a stop reason, or None once the next email may be sent (sleeping as needed)."""
    while True:
        now = ctx.now()
        if _rejection_exceeded(conn, campaign, summary):
            return "bounce_threshold"
        day_count, day_oldest = artemisa_store.attempts_in_last_day(conn, now)
        if day_count >= campaign.daily_cap and day_oldest is not None:
            if not ctx.args.wait_for_window:
                return "daily_cap"
            oldest = datetime.strptime(day_oldest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            frees = oldest + timedelta(hours=24)
            _log(f"daily cap reached; waiting until {_local_text(campaign, frees)}")
            ctx.sleep(max(1.0, (frees - now).total_seconds()))
            continue
        count, oldest = tracking.attempts_in_last_hour(conn, now)
        wait = pacing.cap_wait_seconds(count, oldest, campaign.hourly_cap, now)
        planned = now + timedelta(seconds=wait)
        if not pacing.window_contains(campaign, planned):
            if not ctx.args.wait_for_window:
                return "window_closed"
            _wait_for_window(ctx, campaign, planned)
            continue
        if wait > 0:
            ctx.sleep(wait)
            continue
        return None


def _send_loop(ctx: _Context, conn: sqlite3.Connection, loaded: _Loaded, emails: list[RenderedEmail],
               run_id: int, summary: Summary) -> str:
    campaign = loaded.campaign
    stop_reason = "all_sent"
    consecutive_temporary = 0
    try:
        for index, email in enumerate(emails):
            if index > 0:
                ctx.sleep(pacing.next_interval(campaign, ctx.rng))
            stop = _pre_send_stop(ctx, conn, campaign, summary)
            if stop is not None:
                stop_reason = stop
                break
            sent_at = ctx.now()
            attempt_id = tracking.record_pending(conn, run_id, email.contact_id, campaign.name, 1, _timestamp(sent_at))
            outcome = _send_one(loaded, email, sent_at, ctx.smtp_factory)
            tracking.record_outcome(conn, attempt_id, email.contact_id, outcome, _timestamp(ctx.now()))
            _count(summary, outcome)
            if outcome.stop:
                stop_reason = outcome.error_kind or outcome.status
                break
            if outcome.status == "temporary_failure":
                consecutive_temporary += 1
                if consecutive_temporary >= campaign.temporary_failure_limit:
                    stop_reason = "temporary_failures"
                    break
            else:
                consecutive_temporary = 0
    except KeyboardInterrupt:
        stop_reason = "interrupted"
        raise
    finally:
        tracking.finish_run(conn, run_id, stop_reason, _timestamp(ctx.now()))
        summary.rejected, summary.rejection_base = tracking.campaign_bounce(conn, campaign.name, 1)
        summary.stop_reason = stop_reason
    return stop_reason


if __name__ == "__main__":
    raise SystemExit(main())
