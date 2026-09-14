"""Tests for send runs, attempts, recovery, bounce rate, batch hold and lock (spec 002)."""
import sqlite3
from datetime import datetime, timezone

import pytest

from b2b import store, tracking
from b2b.mailer import SendOutcome

CAMPAIGN = "primer-contacto-2026"


def _conn(db_path):
    conn = store.connect(db_path)
    store.ensure_schema(conn)
    return conn


def outcome(status, error_kind=None, smtp_code=None, message_id=None, stop=False):
    return SendOutcome(status, error_kind, smtp_code, message_id, stop)


ACCEPTED = outcome("accepted", None, 250, "<m@example.com>")


def contact(conn, contact_id):
    return conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()


def attempt(conn, attempt_id):
    return conn.execute("SELECT * FROM send_attempts WHERE id = ?", (attempt_id,)).fetchone()


def test_lock_is_exclusive_and_released(db_path):
    with tracking.send_lock(db_path):
        with pytest.raises(tracking.SendLockBusy):
            with tracking.send_lock(db_path):
                pass
    with tracking.send_lock(db_path):
        pass


def test_run_lifecycle(db_path):
    conn = _conn(db_path)
    run_id = tracking.start_run(conn, CAMPAIGN, 1, True, "2026-09-14T13:00:00Z")
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert (row["kind"], row["campaign"], row["step"], row["forced_no_dmarc"], row["finished_at"]) == (
        "send_production", CAMPAIGN, 1, 1, None)
    tracking.finish_run(conn, run_id, "batch_complete", "2026-09-14T18:00:00Z")
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert (row["finished_at"], row["stop_reason"]) == ("2026-09-14T18:00:00Z", "batch_complete")


def test_pending_then_accepted_updates_contact(contacts_db, db_path):
    [cid] = contacts_db([{"email": "a@example.com"}])
    conn = _conn(db_path)
    run_id = tracking.start_run(conn, CAMPAIGN, 1, False, "2026-09-14T13:00:00Z")
    aid = tracking.record_pending(conn, run_id, cid, CAMPAIGN, 1, "2026-09-14T13:00:05Z")
    row = attempt(conn, aid)
    assert (row["status"], row["finished_at"]) == ("pending", None)
    assert contact(conn, cid)["times_contacted"] == 0

    tracking.record_outcome(conn, aid, cid, ACCEPTED, "2026-09-14T13:00:07Z")
    row = attempt(conn, aid)
    assert (row["status"], row["message_id"], row["smtp_code"], row["finished_at"]) == (
        "accepted", "<m@example.com>", 250, "2026-09-14T13:00:07Z")
    c = contact(conn, cid)
    assert (c["times_contacted"], c["last_contacted_at"], c["bounced"]) == (1, "2026-09-14T13:00:07Z", 0)


def test_second_pending_for_same_contact_and_campaign_rejected(contacts_db, db_path):
    [cid] = contacts_db([{"email": "a@example.com"}])
    conn = _conn(db_path)
    run_id = tracking.start_run(conn, CAMPAIGN, 1, False, "2026-09-14T13:00:00Z")
    tracking.record_pending(conn, run_id, cid, CAMPAIGN, 1, "2026-09-14T13:00:05Z")
    with pytest.raises(sqlite3.IntegrityError):
        tracking.record_pending(conn, run_id, cid, CAMPAIGN, 1, "2026-09-14T13:00:06Z")


def test_permanent_rejection_marks_bounced_once(contacts_db, db_path):
    cids = contacts_db([
        {"email": "a@example.com"},
        {"email": "b@example.com", "bounced": 1, "bounced_at": "2026-09-01T00:00:00Z"},
    ])
    conn = _conn(db_path)
    run_id = tracking.start_run(conn, CAMPAIGN, 1, False, "2026-09-14T13:00:00Z")
    rejected = outcome("permanent_rejection", "recipient_refused", 550)
    for cid in cids:
        aid = tracking.record_pending(conn, run_id, cid, CAMPAIGN, 1, "2026-09-14T13:00:05Z")
        tracking.record_outcome(conn, aid, cid, rejected, "2026-09-14T13:00:06Z")
    assert (contact(conn, cids[0])["bounced"], contact(conn, cids[0])["bounced_at"]) == (1, "2026-09-14T13:00:06Z")
    assert contact(conn, cids[1])["bounced_at"] == "2026-09-01T00:00:00Z"
    assert contact(conn, cids[0])["times_contacted"] == 0


@pytest.mark.parametrize("result", [
    outcome("temporary_failure", "recipient_deferred", 450),
    outcome("unknown", "connection_lost", None, None, True),
])
def test_temporary_and_unknown_do_not_change_contact(contacts_db, db_path, result):
    [cid] = contacts_db([{"email": "a@example.com"}])
    conn = _conn(db_path)
    before = tuple(contact(conn, cid))
    run_id = tracking.start_run(conn, CAMPAIGN, 1, False, "2026-09-14T13:00:00Z")
    aid = tracking.record_pending(conn, run_id, cid, CAMPAIGN, 1, "2026-09-14T13:00:05Z")
    tracking.record_outcome(conn, aid, cid, result, "2026-09-14T13:00:06Z")
    assert tuple(contact(conn, cid)) == before
    assert attempt(conn, aid)["status"] == result.status


def test_outcome_recorded_only_once(contacts_db, db_path):
    [cid] = contacts_db([{"email": "a@example.com"}])
    conn = _conn(db_path)
    run_id = tracking.start_run(conn, CAMPAIGN, 1, False, "2026-09-14T13:00:00Z")
    aid = tracking.record_pending(conn, run_id, cid, CAMPAIGN, 1, "2026-09-14T13:00:05Z")
    tracking.record_outcome(conn, aid, cid, ACCEPTED, "2026-09-14T13:00:06Z")
    with pytest.raises(RuntimeError):
        tracking.record_outcome(conn, aid, cid, ACCEPTED, "2026-09-14T13:00:07Z")
    assert contact(conn, cid)["times_contacted"] == 1
    with pytest.raises(ValueError):
        tracking.record_outcome(conn, aid, cid, outcome("pending"), "2026-09-14T13:00:08Z")


def test_recover_pending(contacts_db, db_path):
    cids = contacts_db([{"email": "a@example.com"}, {"email": "b@example.com"}])
    conn = _conn(db_path)
    run_id = tracking.start_run(conn, CAMPAIGN, 1, False, "2026-09-14T13:00:00Z")
    pending = tracking.record_pending(conn, run_id, cids[0], CAMPAIGN, 1, "2026-09-14T13:00:05Z")
    done = tracking.record_pending(conn, run_id, cids[1], CAMPAIGN, 1, "2026-09-14T13:03:05Z")
    tracking.record_outcome(conn, done, cids[1], ACCEPTED, "2026-09-14T13:03:06Z")
    assert tracking.recover_pending(conn, "2026-09-14T15:00:00Z") == 1
    row = attempt(conn, pending)
    assert (row["status"], row["error_kind"], row["finished_at"]) == ("unknown", "interrupted", "2026-09-14T15:00:00Z")
    assert attempt(conn, done)["status"] == "accepted"
    assert tracking.recover_pending(conn, "2026-09-14T15:01:00Z") == 0


def _run_row(conn, kind, started, finished):
    conn.execute("INSERT INTO runs (kind, campaign, step, started_at, finished_at) VALUES (?, ?, 1, ?, ?)",
                 (kind, CAMPAIGN if kind == "send_production" else None, started, finished))


def test_batch_hold(db_path):
    conn = _conn(db_path)
    assert tracking.batch_hold_satisfied(conn)
    _run_row(conn, "send_production", "2026-09-14T13:00:00Z", "2026-09-14T18:00:00Z")
    assert not tracking.batch_hold_satisfied(conn)
    _run_row(conn, "inbox", "2026-09-14T12:00:00Z", "2026-09-14T12:30:00Z")
    assert not tracking.batch_hold_satisfied(conn)
    _run_row(conn, "inbox", "2026-09-14T19:00:00Z", None)
    assert not tracking.batch_hold_satisfied(conn)
    _run_row(conn, "inbox", "2026-09-14T19:10:00Z", "2026-09-14T19:20:00Z")
    assert tracking.batch_hold_satisfied(conn)


def test_batch_hold_after_crashed_run_uses_start_time(db_path):
    conn = _conn(db_path)
    _run_row(conn, "send_production", "2026-09-15T13:00:00Z", None)
    _run_row(conn, "inbox", "2026-09-15T12:00:00Z", "2026-09-15T12:40:00Z")
    assert not tracking.batch_hold_satisfied(conn)
    _run_row(conn, "inbox", "2026-09-15T14:00:00Z", "2026-09-15T14:05:00Z")
    assert tracking.batch_hold_satisfied(conn)


def test_campaign_bounce_and_threshold(contacts_db, db_path):
    rows = [{"email": f"c{i}@example.com"} for i in range(21)]
    cids = contacts_db(rows)
    conn = _conn(db_path)
    run_id = tracking.start_run(conn, CAMPAIGN, 1, False, "2026-09-14T13:00:00Z")
    for index, cid in enumerate(cids[:19]):
        aid = tracking.record_pending(conn, run_id, cid, CAMPAIGN, 1, f"2026-09-14T13:{index:02d}:00Z")
        tracking.record_outcome(conn, aid, cid, ACCEPTED, f"2026-09-14T13:{index:02d}:01Z")
    # One accepted address later reported bounced (recorded after the manual inbox check), counted in the numerator.
    conn.execute("UPDATE contacts SET bounced = 1, bounced_at = '2026-09-14T14:00:00Z' WHERE id = ?", (cids[0],))
    bounced, base = tracking.campaign_bounce(conn, CAMPAIGN, 1)
    assert (bounced, base) == (1, 19)
    assert not tracking.bounce_exceeded(bounced, base, 0.02, 20)

    aid = tracking.record_pending(conn, run_id, cids[19], CAMPAIGN, 1, "2026-09-14T13:30:00Z")
    tracking.record_outcome(conn, aid, cids[19], outcome("permanent_rejection", "recipient_refused", 550),
                            "2026-09-14T13:30:01Z")
    aid = tracking.record_pending(conn, run_id, cids[20], CAMPAIGN, 1, "2026-09-14T13:31:00Z")
    tracking.record_outcome(conn, aid, cids[20], outcome("temporary_failure", "recipient_deferred", 450),
                            "2026-09-14T13:31:01Z")
    bounced, base = tracking.campaign_bounce(conn, CAMPAIGN, 1)
    assert (bounced, base) == (2, 20)
    assert tracking.bounce_exceeded(bounced, base, 0.02, 20)
    assert tracking.campaign_bounce(conn, "otra-campana", 1) == (0, 0)


def test_bounce_exceeded_boundaries():
    assert not tracking.bounce_exceeded(0, 0, 0.02, 20)
    assert not tracking.bounce_exceeded(2, 100, 0.02, 20)      # exactly 2% is not above
    assert tracking.bounce_exceeded(3, 100, 0.02, 20)


def test_attempts_in_last_hour(contacts_db, db_path):
    cids = contacts_db([{"email": f"h{i}@example.com"} for i in range(3)])
    conn = _conn(db_path)
    run_id = tracking.start_run(conn, CAMPAIGN, 1, False, "2026-09-14T11:00:00Z")
    for cid, created in zip(cids, ["2026-09-14T12:00:00Z", "2026-09-14T12:30:00Z", "2026-09-14T12:59:59Z"]):
        tracking.record_pending(conn, run_id, cid, CAMPAIGN, 1, created)
    now = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)
    assert tracking.attempts_in_last_hour(conn, now) == (2, "2026-09-14T12:30:00Z")
    assert tracking.attempts_in_last_hour(conn, datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)) == (0, None)
