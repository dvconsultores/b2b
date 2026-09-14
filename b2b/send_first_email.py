"""First outreach email: preview, test send and throttled production send (spec 002).

Usage: python -m b2b.send_first_email [--mode preview|test|send] — see
specs/002-first-email-send/contracts/cli.md. Prints counts only; never prints contact values,
credentials or SMTP response text.
"""
from __future__ import annotations

import argparse
import dataclasses
import random
import signal
import sqlite3
import sys
import threading
import time as time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from b2b import ConfigError, pacing, ses_api, store, tracking
from b2b.bounces import apply_suppressions
from b2b.campaign import Campaign, load_campaign
from b2b.eligibility import select_recipients
from b2b.mailer import SenderSettings, SendOutcome, check_login, load_sender_settings, send_email
from b2b.preflight import PreflightResult, check_sender_domain, make_resolver
from b2b.preview import write_preview
from b2b.send_report import SendSummary, format_send_summary
from b2b.template import RenderedEmail, Template, load_template, render, rendered_has_link

PROG = "send_first_email"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_DATABASE = 2
EXIT_REFUSED = 3
EXIT_STOPPED = 4
EXIT_INTERRUPTED = 130

_WEEK = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_SEND_ONLY_OPTIONS = ("force_no_dmarc", "confirm", "wait_for_window", "notify", "ses_guard")


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise _ArgumentError(message)


@dataclasses.dataclass
class _Context:
    args: argparse.Namespace
    smtp_factory: Callable | None
    resolver: object | None
    now: Callable[[], datetime]
    sleep: Callable[[float], None]
    ask: Callable[[str], str]
    rng: random.Random
    ses_clients: object | None = None


def _error(message: str) -> None:
    print(f"{PROG}: error: {message}", file=sys.stderr)


def _log(message: str) -> None:
    print(f"{PROG}: {message}", flush=True)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(prog=f"python -m b2b.{PROG}", description="Preview, test or send the first outreach email.")
    parser.add_argument("--mode", choices=("preview", "test", "send"), default="preview")
    parser.add_argument("--config", default="config/campaign.toml")
    parser.add_argument("--db", default="data/b2b.sqlite3")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--previews-dir", default="data/previews")
    parser.add_argument("--force-no-dmarc", action="store_true")
    parser.add_argument("--confirm", metavar="CAMPAIGN", default=None,
                        help="send mode: confirm the campaign name at launch instead of typing it")
    parser.add_argument("--wait-for-window", action="store_true",
                        help="send mode: sleep until the send window opens instead of stopping")
    parser.add_argument("--notify", action="store_true",
                        help="send mode: email the counts-only summary to TEST_RECIPIENTS when the run ends")
    parser.add_argument("--ses-guard", action="store_true",
                        help="send mode: sync bounces from the SES API and pause on the real bounce rate")
    args = parser.parse_args(argv)
    if args.mode != "send":
        for name in _SEND_ONLY_OPTIONS:
            value = getattr(args, name)
            if value not in (None, False):
                raise _ArgumentError(f"--{name.replace('_', '-')} is only allowed with --mode send")
    return args


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv: list[str] | None = None, *, smtp_factory=None, resolver=None, now=None,
         sleep=None, ask=None, rng=None, ses_clients=None) -> int:
    try:
        args = _parse_args(argv)
    except _ArgumentError as exc:
        _error(str(exc))
        return EXIT_CONFIG
    ctx = _Context(
        args=args,
        smtp_factory=smtp_factory,
        resolver=resolver,
        now=now or (lambda: datetime.now(timezone.utc)),
        sleep=sleep or time_module.sleep,
        ask=ask or input,
        rng=rng or random.Random(),
        ses_clients=ses_clients,
    )
    # docker stop / Watchtower send SIGTERM: treat it like Ctrl+C so the run is closed cleanly.
    previous_handler = None
    if args.mode == "send" and threading.current_thread() is threading.main_thread():
        previous_handler = signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
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


# --- shared setup ---------------------------------------------------------------------------


def _load(ctx: _Context) -> tuple[Campaign, Template, SenderSettings]:
    """Config, template, launch-price date and .env settings. Raises ConfigError or OSError."""
    config_path = Path(ctx.args.config)
    campaign = load_campaign(config_path)
    template = load_template(campaign.template, campaign.phrases.opt_out)
    if pacing.launch_price_passed(campaign, ctx.now()):
        raise ConfigError(f"{config_path}: launch_price_end {campaign.launch_price_end.isoformat()} has passed")
    needs_recipients = ctx.args.mode == "test" or ctx.args.notify
    settings = load_sender_settings(Path(ctx.args.env), require_test_recipients=needs_recipients)
    return campaign, template, settings


def _load_or_report(ctx: _Context):
    try:
        return _load(ctx)
    except ConfigError as exc:
        _error(str(exc))
    except OSError as exc:
        _error(f"{exc.filename}: cannot read file")
    return None


def _open_database(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.is_file():
        _error(f"{db_path}: database not found")
        return None
    try:
        conn = store.connect(db_path)
        store.ensure_schema(conn)
        return conn
    except store.SchemaError as exc:
        _error(str(exc))
    except sqlite3.Error as exc:
        _error(f"{db_path}: database error ({type(exc).__name__})")
    return None


def _render_batch(campaign: Campaign, template: Template, settings: SenderSettings, conn: sqlite3.Connection,
                  summary: SendSummary) -> list[RenderedEmail]:
    selection = select_recipients(conn, campaign.name, campaign.step, campaign.allowed_verification)
    emails: list[RenderedEmail] = []
    for recipient in selection.recipients:
        email = render(
            template,
            campaign.phrases,
            to=recipient.email,
            contact_id=recipient.contact_id,
            company=recipient.company,
            contact_name=recipient.contact_name,
            city=recipient.city,
            sender_name=settings.from_name,
        )
        if rendered_has_link(email):
            summary.skipped_rendered_link += 1
            continue
        emails.append(email)
    batch = emails[: campaign.batch_limit]
    summary.eligible = selection.eligible
    summary.skipped_not_verified = selection.skipped_not_verified
    summary.skipped_same_company = selection.skipped_same_company
    summary.selected = len(batch)
    return batch


def _local_text(campaign: Campaign, moment: datetime) -> str:
    return f"{pacing.local_now(campaign, moment):%Y-%m-%d %H:%M} {campaign.timezone}"


def _dmarc_text(preflight: PreflightResult) -> str:
    if preflight.dmarc == "present" and preflight.dmarc_policy:
        return f"present (p={preflight.dmarc_policy})"
    return preflight.dmarc


def _preflight(ctx: _Context, settings: SenderSettings) -> PreflightResult:
    resolver = ctx.resolver if ctx.resolver is not None else make_resolver()
    return check_sender_domain(settings.sender.rsplit("@", 1)[1], resolver)


def _print_summary(summary: SendSummary) -> None:
    print(format_send_summary(summary), end="", flush=True)


def _count(summary: SendSummary, outcome: SendOutcome) -> None:
    if outcome.status == "accepted":
        summary.accepted += 1
    elif outcome.status == "permanent_rejection":
        summary.permanent_rejections += 1
    elif outcome.status == "temporary_failure":
        summary.temporary_failures += 1
    else:
        summary.unknown += 1


# --- preview --------------------------------------------------------------------------------


def _preview(ctx: _Context) -> int:
    loaded = _load_or_report(ctx)
    if loaded is None:
        return EXIT_CONFIG
    campaign, template, settings = loaded
    conn = _open_database(Path(ctx.args.db))
    if conn is None:
        return EXIT_DATABASE
    try:
        summary = SendSummary("preview", "done", campaign.name, campaign.step)
        batch = _render_batch(campaign, template, settings, conn, summary)
    finally:
        conn.close()
    path = write_preview(Path(ctx.args.previews_dir), campaign, batch, ctx.now())
    summary.previewed = len(batch)
    summary.preview_path = str(path)
    if not batch:
        summary.result = "nothing_to_send"
    _print_summary(summary)
    return EXIT_OK


# --- test send ------------------------------------------------------------------------------


def _test_send(ctx: _Context) -> int:
    loaded = _load_or_report(ctx)
    if loaded is None:
        return EXIT_CONFIG
    campaign, template, settings = loaded
    summary = SendSummary("test", "done", campaign.name, campaign.step)

    preflight = _preflight(ctx, settings)
    summary.dmarc, summary.spf = _dmarc_text(preflight), preflight.spf

    sample = campaign.test_sample
    variants = [(sample.nombre, sample.ciudad), ("", sample.ciudad), (sample.nombre, "")]
    recipients = settings.test_recipients
    for index, (name, city) in enumerate(variants[: campaign.test_sample_count]):
        email = render(
            template,
            campaign.phrases,
            to=recipients[index % len(recipients)],
            contact_id=None,
            company=sample.empresa,
            contact_name=name,
            city=city,
            sender_name=settings.from_name,
        )
        email = dataclasses.replace(email, subject=f"[PRUEBA] {email.subject}")
        outcome = send_email(settings, email, ctx.now(), ctx.smtp_factory)
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


def _window_text(campaign: Campaign) -> str:
    days = list(campaign.send_days)
    indexes = sorted(_WEEK.index(day) for day in days)
    if len(indexes) > 1 and indexes == list(range(indexes[0], indexes[-1] + 1)):
        day_text = f"{_WEEK[indexes[0]]}–{_WEEK[indexes[-1]]}"
    else:
        day_text = ",".join(_WEEK[i] for i in indexes)
    return f"{day_text} {campaign.send_start:%H:%M}–{campaign.send_end:%H:%M} {campaign.timezone}"


def _wait_for_window(ctx: _Context, campaign: Campaign, moment: datetime) -> None:
    now = ctx.now()
    opens = pacing.next_window_start(campaign, moment)
    _log(f"waiting for the send window to open at {_local_text(campaign, opens)}")
    ctx.sleep(max(0.0, (opens - now).total_seconds()))


def _notify(ctx: _Context, settings: SenderSettings, summary: SendSummary) -> None:
    """Email the counts-only summary to the operator's TEST_RECIPIENTS."""
    subject = f"[b2b] {summary.campaign}: {summary.result} ({summary.stop_reason})"
    body = format_send_summary(summary)
    for recipient in settings.test_recipients:
        notice = RenderedEmail(contact_id=None, to=recipient, subject=subject, body=body)
        outcome = send_email(settings, notice, ctx.now(), ctx.smtp_factory)
        if outcome.status != "accepted":
            _error(f"summary email not sent ({outcome.error_kind or outcome.status})")


class _SesGuard:
    """Live bounce protection from the SES API (spec 003).

    SES accepts every email at SMTP time and reports bounces later, so before each email the
    contact database is refreshed from the suppression list and the real bounce rate is checked.
    """

    def __init__(self, clients, campaign: Campaign):
        self.clients = clients
        self.campaign = campaign

    def sync(self, conn: sqlite3.Connection):
        return apply_suppressions(conn, ses_api.list_suppressed(self.clients))

    def rate_exceeded(self, since: datetime) -> bool:
        stats = ses_api.send_statistics(self.clients, since)
        return tracking.bounce_exceeded(stats.bounces, stats.attempts,
                                        self.campaign.bounce_pause_threshold, self.campaign.bounce_min_sends)


def _production_locked(ctx: _Context, db_path: Path) -> int:
    loaded = _load_or_report(ctx)
    if loaded is None:
        return EXIT_CONFIG
    campaign, template, settings = loaded
    conn = _open_database(db_path)
    if conn is None:
        return EXIT_DATABASE
    try:
        summary = SendSummary("send", "refused", campaign.name, campaign.step)
        tracking.recover_pending(conn, _timestamp(ctx.now()))

        if not tracking.batch_hold_satisfied(conn):
            _error("batch hold: check the inbox (bounces, replies, opt-outs) and run "
                   "python -m b2b.mark_inbox_checked before the next production batch")
            _print_summary(summary)
            return EXIT_REFUSED

        guard = None
        if ctx.args.ses_guard:
            try:
                clients = ctx.ses_clients
                if clients is None:
                    clients = ses_api.make_clients(ses_api.load_aws_settings(Path(ctx.args.env)))
                guard = _SesGuard(clients, campaign)
                synced = guard.sync(conn)
                _log(f"SES bounce sync: {synced.newly_bounced} newly bounced, "
                     f"{synced.newly_opted_out} newly opted out")
                if guard.rate_exceeded(ctx.now() - timedelta(hours=24)):
                    summary.stop_reason = "ses_bounce_rate"
                    _error("SES bounce rate in the last 24 hours is above the pause threshold; sending stays paused")
                    _print_summary(summary)
                    return EXIT_REFUSED
            except ConfigError as exc:
                _error(str(exc))
                return EXIT_CONFIG
            except ses_api.SesApiError as exc:
                _error(f"SES API check failed ({exc})")
                return EXIT_CONFIG

        summary.bounced, summary.bounce_base = tracking.campaign_bounce(conn, campaign.name, campaign.step)
        if tracking.bounce_exceeded(summary.bounced, summary.bounce_base,
                                    campaign.bounce_pause_threshold, campaign.bounce_min_sends):
            summary.stop_reason = "bounce_threshold"
            _error("campaign bounce rate is above the pause threshold; sending stays paused")
            _print_summary(summary)
            return EXIT_REFUSED

        login_error = check_login(settings, ctx.smtp_factory)
        if login_error is not None:
            _error(f"SMTP login check failed ({login_error})")
            return EXIT_CONFIG

        preflight = _preflight(ctx, settings)
        summary.dmarc, summary.spf = _dmarc_text(preflight), preflight.spf
        forced = ctx.args.force_no_dmarc and preflight.dmarc != "present"
        summary.forced_no_dmarc = forced
        if preflight.dmarc != "present" and not ctx.args.force_no_dmarc:
            _error("DMARC not present for sender domain; publish it or pass --force-no-dmarc")
            _print_summary(summary)
            return EXIT_REFUSED

        now = ctx.now()
        if not pacing.window_contains(campaign, now):
            if not ctx.args.wait_for_window:
                summary.result = "outside_window"
                summary.next_window = _local_text(campaign, pacing.next_window_start(campaign, now))
                _print_summary(summary)
                return EXIT_OK
            _wait_for_window(ctx, campaign, now)

        batch = _render_batch(campaign, template, settings, conn, summary)
        if not batch:
            summary.result = "nothing_to_send"
            _print_summary(summary)
            return EXIT_OK

        print(f"campaign:        {campaign.name} (step {campaign.step})")
        print(f"recipients:      {len(batch)}")
        print(f"hourly cap:      {campaign.hourly_cap} per hour")
        print(f"batch limit:     {campaign.batch_limit}")
        print(f"send window:     {_window_text(campaign)}")
        print(f"DMARC:           {summary.dmarc}")
        print(f"SPF:             {summary.spf}")
        print(f"forced no DMARC: {'yes' if forced else 'no'}", flush=True)
        if ctx.args.confirm is not None:
            answer = ctx.args.confirm
            _log("confirmation supplied at launch (--confirm)")
        else:
            answer = ctx.ask("Type the campaign name to start sending: ")
        if (answer or "").strip() != campaign.name:
            _error("confirmation does not match the campaign name; nothing was sent")
            _print_summary(summary)
            return EXIT_REFUSED

        run_started = ctx.now()
        run_id = tracking.start_run(conn, campaign.name, campaign.step, forced, _timestamp(run_started))
        try:
            stop_reason = _send_loop(ctx, conn, campaign, settings, batch, run_id, summary, guard, run_started)
        except KeyboardInterrupt:
            summary.result = "stopped"
            if ctx.args.notify:
                _notify(ctx, settings, summary)
            raise
        summary.result = "done" if stop_reason == "batch_complete" else "stopped"
        if stop_reason != "batch_complete":
            _error(f"sending stopped ({stop_reason})")
        _print_summary(summary)
        if ctx.args.notify:
            _notify(ctx, settings, summary)
        return EXIT_OK if stop_reason == "batch_complete" else EXIT_STOPPED
    finally:
        conn.close()


def _pre_send_stop(ctx: _Context, conn: sqlite3.Connection, campaign: Campaign,
                   guard: _SesGuard | None = None, run_started: datetime | None = None) -> str | None:
    """Return a stop reason, or None once the next email may be sent (sleeping as needed)."""
    while True:
        now = ctx.now()
        if pacing.launch_price_passed(campaign, now):
            return "launch_price_ended"
        if guard is not None:
            try:
                guard.sync(conn)
                if guard.rate_exceeded(run_started or now):
                    return "ses_bounce_rate"
            except ses_api.SesApiError:
                return "ses_check_failed"
        bounced, base = tracking.campaign_bounce(conn, campaign.name, campaign.step)
        if tracking.bounce_exceeded(bounced, base, campaign.bounce_pause_threshold, campaign.bounce_min_sends):
            return "bounce_threshold"
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


def _send_loop(ctx: _Context, conn: sqlite3.Connection, campaign: Campaign, settings: SenderSettings,
               batch: list[RenderedEmail], run_id: int, summary: SendSummary,
               guard: _SesGuard | None = None, run_started: datetime | None = None) -> str:
    stop_reason = "batch_complete"
    consecutive_temporary = 0
    try:
        for index, email in enumerate(batch):
            if index > 0:
                ctx.sleep(pacing.next_interval(campaign, ctx.rng))
            stop = _pre_send_stop(ctx, conn, campaign, guard, run_started)
            if stop is not None:
                stop_reason = stop
                break
            sent_at = ctx.now()
            attempt_id = tracking.record_pending(conn, run_id, email.contact_id, campaign.name, campaign.step,
                                                 _timestamp(sent_at))
            outcome = send_email(settings, email, sent_at, ctx.smtp_factory)
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
        if guard is not None:
            try:
                guard.sync(conn)  # include bounces that arrived during the run in the summary
            except ses_api.SesApiError:
                pass
        summary.bounced, summary.bounce_base = tracking.campaign_bounce(conn, campaign.name, campaign.step)
        summary.stop_reason = stop_reason
    return stop_reason


if __name__ == "__main__":
    raise SystemExit(main())
