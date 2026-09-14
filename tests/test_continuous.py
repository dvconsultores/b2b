"""Spec 005: continuous campaigns and waiting for the SES 24-hour bounce rate (fakes only)."""
import random
from datetime import timedelta

from test_send_first_email import CAMPAIGN, fake_resolver, query, recipients, setup, summary_of  # noqa: F401
from test_ses_guard import AWS, FakeSes

from b2b.send_first_email import main


def run(s, clock, smtp_factory, *extra, ses=None):
    argv = ["--mode", "send", "--config", str(s.config), "--db", str(s.db), "--env", str(s.env),
            "--previews-dir", str(s.previews), "--confirm", CAMPAIGN, *extra]
    return main(argv, smtp_factory=smtp_factory, resolver=fake_resolver(), now=clock.now, sleep=clock.sleep,
                ask=lambda _prompt: "", rng=random.Random(0), ses_clients=ses)


def test_continuous_campaign_sends_batch_after_batch(setup, fake_clock, fake_smtp, capsys):
    s = setup(batch_limit="1", continuous="true")
    factory, log = fake_smtp()
    assert run(s, fake_clock, factory) == 0
    assert len(log.messages) == 3
    assert query(s.db, "SELECT stop_reason FROM runs ORDER BY id") == [
        ("batch_complete",), ("batch_complete",), ("batch_complete",)]
    values = summary_of(capsys.readouterr().out)
    assert (values["stop reason"], values["selected"], values["accepted"]) == ("all_sent", "3", "3")


def test_single_batch_when_not_continuous(setup, fake_clock, fake_smtp):
    s = setup(batch_limit="1", continuous="false")
    factory, log = fake_smtp()
    assert run(s, fake_clock, factory) == 0
    assert len(log.messages) == 1
    assert query(s.db, "SELECT stop_reason FROM runs") == [("batch_complete",)]


def test_continuous_stops_on_bounces_across_batches(setup, fake_clock, fake_smtp, capsys):
    s = setup(env=AWS, batch_limit="1", continuous="true", bounce_min_sends="2")
    factory, log = fake_smtp()
    ses = FakeSes(fake_clock, log=log, bounce={"ana@example.com"})
    assert run(s, fake_clock, factory, "--ses-guard", ses=ses) == 4
    assert len(log.messages) == 2
    assert summary_of(capsys.readouterr().out)["stop reason"] == "ses_bounce_rate"


def test_launch_waits_for_24h_bounce_rate_to_fall(setup, fake_clock, fake_smtp, capsys):
    s = setup(env=AWS)
    factory, log = fake_smtp()
    started = fake_clock.now()

    class Recovering(FakeSes):
        def get_send_statistics(self):
            high = self.clock.now() < started + timedelta(hours=1)
            return {"SendDataPoints": [{"Timestamp": self.clock.now(), "DeliveryAttempts": 65 if high else 0,
                                        "Bounces": 10 if high else 0, "Complaints": 0, "Rejects": 0}]}

    assert run(s, fake_clock, factory, "--ses-guard", "--wait-for-window", ses=Recovering(fake_clock, log=log)) == 0
    assert len(log.messages) == 3
    assert fake_clock.now() - started >= timedelta(hours=1)
    assert "checking again in 30 minutes" in capsys.readouterr().out
