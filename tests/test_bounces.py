"""Spec 003: SES API wrapper, suppression sync and the sync_bounces command (fakes, no network)."""
import sqlite3
from datetime import datetime, timezone

import pytest

from b2b import ConfigError, store
from b2b.bounces import apply_suppressions
from b2b.ses_api import SesApiError, SesClients, Suppressed, list_suppressed, load_aws_settings, send_statistics
from b2b.sync_bounces import main as sync_main

T = datetime(2026, 9, 14, 15, 30, tzinfo=timezone.utc)
AWS = {"AWS_ACCESS_KEY_ID": "AKIAEXAMPLEEXAMPLE", "AWS_SECRET_ACCESS_KEY": "example-secret", "AWS_REGION": "us-east-2"}


def tracking_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {row[0]: row[1:] for row in conn.execute(
            "SELECT email, bounced, bounced_at, opted_out, opted_out_at FROM contacts")}
    finally:
        conn.close()


SUPPRESSED = [
    Suppressed("a@example.com", "BOUNCE", T),
    Suppressed("b@example.com", "BOUNCE", T),
    Suppressed("c@example.com", "COMPLAINT", T),
    Suppressed("x@example.net", "BOUNCE", T),
    Suppressed("d@example.com", "OTHER", T),
]


@pytest.fixture
def three_contacts(contacts_db):
    return contacts_db([
        {"email": "a@example.com"},
        {"email": "b@example.com", "bounced": 1, "bounced_at": "2026-09-01T00:00:00Z"},
        {"email": "c@example.com"},
        {"email": "d@example.com"},
    ])


# --- apply_suppressions ---------------------------------------------------------------------------


def test_apply_marks_bounces_and_complaints_once(three_contacts, db_path):
    conn = store.connect(db_path)
    result = apply_suppressions(conn, SUPPRESSED)
    assert (result.suppressed, result.matched, result.newly_bounced, result.newly_opted_out,
            result.already_marked, result.not_in_database, result.ignored) == (5, 4, 1, 1, 1, 1, 1)
    rows = tracking_rows(db_path)
    assert rows["a@example.com"] == (1, "2026-09-14T15:30:00Z", 0, None)
    assert rows["b@example.com"][:2] == (1, "2026-09-01T00:00:00Z")
    assert rows["c@example.com"] == (0, None, 1, "2026-09-14T15:30:00Z")
    assert rows["d@example.com"] == (0, None, 0, None)

    again = apply_suppressions(conn, SUPPRESSED)
    assert (again.newly_bounced, again.newly_opted_out, again.already_marked) == (0, 0, 3)
    assert tracking_rows(db_path) == rows


def test_apply_dry_run_writes_nothing(three_contacts, db_path):
    before = tracking_rows(db_path)
    result = apply_suppressions(store.connect(db_path), SUPPRESSED, dry_run=True)
    assert (result.newly_bounced, result.newly_opted_out) == (1, 1)
    assert tracking_rows(db_path) == before


# --- ses_api --------------------------------------------------------------------------------------


class PagedSesV2:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list_suppressed_destinations(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages[len(self.calls) - 1]


def test_list_suppressed_pages_and_normalizes():
    naive = datetime(2026, 9, 14, 15, 30)
    sesv2 = PagedSesV2([
        {"SuppressedDestinationSummaries": [{"EmailAddress": " Ana@Example.COM ", "Reason": "BOUNCE", "LastUpdateTime": T}],
         "NextToken": "t1"},
        {"SuppressedDestinationSummaries": [{"EmailAddress": "luis@example.org", "Reason": "COMPLAINT", "LastUpdateTime": naive}]},
    ])
    result = list_suppressed(SesClients(sesv2=sesv2, ses=None))
    assert result == [Suppressed("ana@example.com", "BOUNCE", T), Suppressed("luis@example.org", "COMPLAINT", T)]
    assert sesv2.calls == [{"PageSize": 1000}, {"PageSize": 1000, "NextToken": "t1"}]


class StatsSes:
    def get_send_statistics(self):
        return {"SendDataPoints": [
            {"Timestamp": datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc), "DeliveryAttempts": 50, "Bounces": 1, "Complaints": 0, "Rejects": 0},
            {"Timestamp": datetime(2026, 9, 14, 12, 15, tzinfo=timezone.utc), "DeliveryAttempts": 30, "Bounces": 4, "Complaints": 1, "Rejects": 0},
            {"Timestamp": datetime(2026, 9, 14, 12, 30, tzinfo=timezone.utc), "DeliveryAttempts": 35, "Bounces": 6, "Complaints": 0, "Rejects": 2},
        ]}


def test_send_statistics_sums_points_since():
    stats = send_statistics(SesClients(sesv2=None, ses=StatsSes()), datetime(2026, 9, 14, tzinfo=timezone.utc))
    assert (stats.attempts, stats.bounces, stats.complaints, stats.rejects) == (65, 10, 1, 2)


def test_api_errors_carry_code_only():
    class AccessDenied(Exception):
        response = {"Error": {"Code": "AccessDeniedException", "Message": "user arn:aws:iam::1:user/x is not authorized"}}

    class Broken:
        def get_send_statistics(self):
            raise AccessDenied("details with arn")

    with pytest.raises(SesApiError) as excinfo:
        send_statistics(SesClients(sesv2=None, ses=Broken()), T)
    assert str(excinfo.value) == "AccessDeniedException"


def test_load_aws_settings(send_env):
    settings = load_aws_settings(send_env(**AWS))
    assert (settings.access_key_id, settings.region) == ("AKIAEXAMPLEEXAMPLE", "us-east-2")
    assert "example-secret" not in repr(settings)


@pytest.mark.parametrize("overrides, key", [
    ({}, "AWS_ACCESS_KEY_ID"),
    ({"AWS_ACCESS_KEY_ID": "<access key>", "AWS_SECRET_ACCESS_KEY": "x"}, "AWS_ACCESS_KEY_ID"),
    ({"AWS_ACCESS_KEY_ID": "AKIAEXAMPLEEXAMPLE", "AWS_SECRET_ACCESS_KEY": "<secret access key>"}, "AWS_SECRET_ACCESS_KEY"),
])
def test_load_aws_settings_missing(send_env, overrides, key):
    path = send_env(**overrides)
    with pytest.raises(ConfigError, match=f"missing {key}"):
        load_aws_settings(path)


# --- sync_bounces command -------------------------------------------------------------------------


class FakeClients:
    def __init__(self, entries=(), error=None):
        self.sesv2 = self
        self.ses = self
        self.entries = list(entries)
        self.error = error

    def list_suppressed_destinations(self, **kwargs):
        if self.error:
            raise self.error
        return {"SuppressedDestinationSummaries": [
            {"EmailAddress": s.email, "Reason": s.reason, "LastUpdateTime": s.updated_at} for s in self.entries]}


def test_sync_command_prints_counts_only(three_contacts, db_path, send_env, capsys):
    env = send_env(**AWS)
    assert sync_main(["--db", str(db_path), "--env", str(env)], clients=FakeClients(SUPPRESSED)) == 0
    out = capsys.readouterr().out
    assert out == ("sync_bounces: suppressed 5 | matched 4 | newly bounced 1 | newly opted out 1 | "
                   "already marked 1 | not in database 1\n")
    assert "@" not in out
    assert tracking_rows(db_path)["a@example.com"][0] == 1


def test_sync_command_dry_run(three_contacts, db_path, send_env, capsys):
    before = tracking_rows(db_path)
    assert sync_main(["--db", str(db_path), "--env", str(send_env(**AWS)), "--dry-run"],
                     clients=FakeClients(SUPPRESSED)) == 0
    assert capsys.readouterr().out.rstrip().endswith("dry run, nothing written")
    assert tracking_rows(db_path) == before


def test_sync_command_errors(three_contacts, db_path, send_env, tmp_path, capsys):
    assert sync_main(["--db", str(tmp_path / "missing.sqlite3"), "--env", str(send_env(**AWS))],
                     clients=FakeClients()) == 2
    assert sync_main(["--db", str(db_path), "--env", str(send_env())]) == 1
    assert "missing AWS_ACCESS_KEY_ID" in capsys.readouterr().err

    class Denied(Exception):
        response = {"Error": {"Code": "AccessDeniedException"}}

    assert sync_main(["--db", str(db_path), "--env", str(send_env(**AWS))], clients=FakeClients(error=Denied())) == 1
    assert "SES API error (AccessDeniedException)" in capsys.readouterr().err
