"""Spec 003: live SES bounce guard in production sending (fake SMTP, fake SES, no network)."""
import random

from test_send_first_email import CAMPAIGN, fake_resolver, query, recipients, setup, summary_of  # noqa: F401

from b2b.send_first_email import main

AWS = {"AWS_ACCESS_KEY_ID": "AKIAEXAMPLEEXAMPLE", "AWS_SECRET_ACCESS_KEY": "example-secret", "AWS_REGION": "us-east-2"}


class FakeSes:
    """Suppression list and statistics derived from what the fake SMTP server has 'sent'."""

    def __init__(self, clock, log=None, bounce=(), stats=None, fail_after_sends=None):
        self.sesv2 = self
        self.ses = self
        self.clock = clock
        self.log = log
        self.bounce = set(bounce)
        self.stats = stats
        self.fail_after_sends = fail_after_sends

    def _sent(self):
        return [to_addrs[0] for _from, to_addrs, _msg in self.log.messages] if self.log else []

    def _maybe_fail(self):
        if self.fail_after_sends is not None and len(self._sent()) >= self.fail_after_sends:
            raise ConnectionError("simulated SES API failure")

    def list_suppressed_destinations(self, **kwargs):
        self._maybe_fail()
        return {"SuppressedDestinationSummaries": [
            {"EmailAddress": address.upper(), "Reason": "BOUNCE", "LastUpdateTime": self.clock.now()}
            for address in self._sent() if address in self.bounce]}

    def get_send_statistics(self):
        self._maybe_fail()
        if self.stats is not None:
            attempts, bounces = self.stats
        else:
            sent = self._sent()
            attempts, bounces = len(sent), sum(1 for address in sent if address in self.bounce)
        return {"SendDataPoints": [{"Timestamp": self.clock.now(), "DeliveryAttempts": attempts,
                                    "Bounces": bounces, "Complaints": 0, "Rejects": 0}]}


def never_ask(_prompt):
    raise AssertionError("must not prompt")


def run_guarded(s, clock, smtp_factory, ses, *extra):
    argv = ["--mode", "send", "--config", str(s.config), "--db", str(s.db), "--env", str(s.env),
            "--previews-dir", str(s.previews), "--confirm", CAMPAIGN, "--ses-guard", *extra]
    return main(argv, smtp_factory=smtp_factory, resolver=fake_resolver(), now=clock.now, sleep=clock.sleep,
                ask=never_ask, rng=random.Random(0), ses_clients=ses)


def test_guard_requires_aws_keys(setup, fake_clock, fake_smtp, capsys):
    s = setup()
    factory, log = fake_smtp()
    assert run_guarded(s, fake_clock, factory, None) == 1
    assert "missing AWS_ACCESS_KEY_ID" in capsys.readouterr().err
    assert log.connects == 0


def test_guard_refuses_when_last_24h_bounce_rate_is_high(setup, fake_clock, fake_smtp, capsys):
    s = setup(env=AWS)
    factory, log = fake_smtp()
    assert run_guarded(s, fake_clock, factory, FakeSes(fake_clock, stats=(65, 10))) == 3
    captured = capsys.readouterr()
    assert "SES bounce rate in the last 24 hours" in captured.err
    assert summary_of(captured.out)["stop reason"] == "ses_bounce_rate"
    assert log.connects == 0 and query(s.db, "SELECT COUNT(*) FROM runs") == [(0,)]


def test_guard_stops_mid_batch_and_records_bounce(setup, fake_clock, fake_smtp, capsys):
    s = setup(env=AWS, bounce_min_sends="2")
    factory, log = fake_smtp()
    ses = FakeSes(fake_clock, log=log, bounce={"ana@example.com"})
    assert run_guarded(s, fake_clock, factory, ses) == 4
    assert recipients(log) == ["ana@example.com", "luis@example.org"]
    values = summary_of(capsys.readouterr().out)
    assert (values["stop reason"], values["campaign bounce rate"]) == ("ses_bounce_rate", "50.0% (1 of 2)")
    assert query(s.db, "SELECT bounced FROM contacts WHERE email = 'ana@example.com'") == [(1,)]
    assert query(s.db, "SELECT stop_reason FROM runs") == [("ses_bounce_rate",)]


def test_guard_stops_when_ses_api_fails(setup, fake_clock, fake_smtp, capsys):
    s = setup(env=AWS)
    factory, log = fake_smtp()
    assert run_guarded(s, fake_clock, factory, FakeSes(fake_clock, log=log, fail_after_sends=1)) == 4
    assert recipients(log) == ["ana@example.com"]
    assert summary_of(capsys.readouterr().out)["stop reason"] == "ses_check_failed"


def test_guard_clean_batch_completes(setup, fake_clock, fake_smtp):
    s = setup(env=AWS)
    factory, log = fake_smtp()
    assert run_guarded(s, fake_clock, factory, FakeSes(fake_clock, log=log)) == 0
    assert len(log.messages) == 3
    assert query(s.db, "SELECT stop_reason FROM runs") == [("batch_complete",)]


def test_ses_guard_is_send_only(setup, fake_clock, capsys):
    s = setup(env=AWS)
    argv = ["--mode", "preview", "--config", str(s.config), "--db", str(s.db), "--env", str(s.env),
            "--previews-dir", str(s.previews), "--ses-guard"]
    assert main(argv, now=fake_clock.now) == 1
    assert "only allowed with --mode send" in capsys.readouterr().err
