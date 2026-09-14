"""Tests for first-email recipient selection (spec 002 plan D8, spec 004 plan D3)."""
from b2b import store
from b2b.eligibility import select_recipients, verification_candidates

CAMPAIGN = "primer-contacto-2026"


def _conn(db_path):
    conn = store.connect(db_path)
    store.ensure_schema(conn)
    return conn


def _run(conn, campaign=CAMPAIGN):
    return conn.execute(
        "INSERT INTO runs (kind, campaign, step, started_at) VALUES ('send_production', ?, 1, '2026-09-14T13:00:00Z')",
        (campaign,),
    ).lastrowid


def _attempt(conn, contact_id, status, campaign=CAMPAIGN):
    run_id = _run(conn, campaign)
    finished = None if status == "pending" else "2026-09-14T13:01:00Z"
    message_id = "<m@example.com>" if status == "accepted" else None
    conn.execute(
        "INSERT INTO send_attempts (run_id, contact_id, campaign, step, status, message_id, created_at, finished_at) "
        "VALUES (?, ?, ?, 1, ?, ?, '2026-09-14T13:00:00Z', ?)",
        (run_id, contact_id, campaign, status, message_id, finished),
    )


def _emails(selection):
    return [r.email for r in selection.recipients]


def test_all_eligible_one_per_company(contacts_db, db_path):
    contacts_db([
        {"email": "a@example.com", "company_key": "n:uno"},
        {"email": "b@example.com", "company_key": "n:dos"},
    ])
    selection = select_recipients(_conn(db_path), CAMPAIGN, 1)
    assert _emails(selection) == ["a@example.com", "b@example.com"]
    assert (selection.eligible, selection.skipped_same_company) == (2, 0)


def test_excluded_contacts(contacts_db, db_path):
    contacts_db([
        {"email": "ok@example.com", "company_key": "n:ok"},
        {"email": "contacted@example.com", "company_key": "n:c1", "times_contacted": 1,
         "last_contacted_at": "2026-09-01T00:00:00Z"},
        {"email": "bounced@example.com", "company_key": "n:c2", "bounced": 1, "bounced_at": "2026-09-01T00:00:00Z"},
        {"email": "responded@example.com", "company_key": "n:c3", "responded": 1,
         "responded_at": "2026-09-01T00:00:00Z"},
        {"email": "optout@example.com", "company_key": "n:c4", "opted_out": 1, "opted_out_at": "2026-09-01T00:00:00Z"},
        {"email": "info@example.com", "company_key": "n:c5", "classification": "generic"},
    ])
    selection = select_recipients(_conn(db_path), CAMPAIGN, 1)
    assert _emails(selection) == ["ok@example.com"]
    assert selection.eligible == 1


def test_attempt_in_campaign_excludes_contact_whatever_status(contacts_db, db_path):
    ids = contacts_db([
        {"email": "temp@example.com", "company_key": "n:t"},
        {"email": "ok@example.com", "company_key": "n:ok"},
    ])
    conn = _conn(db_path)
    _attempt(conn, ids[0], "temporary_failure")
    assert _emails(select_recipients(conn, CAMPAIGN, 1)) == ["ok@example.com"]


def test_unknown_attempt_in_other_campaign_excludes_contact(contacts_db, db_path):
    ids = contacts_db([
        {"email": "unknown@example.com", "company_key": "n:u"},
        {"email": "temp-other@example.com", "company_key": "n:t"},
    ])
    conn = _conn(db_path)
    _attempt(conn, ids[0], "unknown", campaign="otra-campana")
    _attempt(conn, ids[1], "temporary_failure", campaign="otra-campana")
    assert _emails(select_recipients(conn, CAMPAIGN, 1)) == ["temp-other@example.com"]


def test_company_with_accepted_attempt_in_campaign_is_excluded(contacts_db, db_path):
    ids = contacts_db([
        {"email": "sent@example.com", "company_key": "n:empresa", "times_contacted": 1,
         "last_contacted_at": "2026-09-14T13:01:00Z"},
        {"email": "colleague@example.com", "company_key": "n:empresa"},
        {"email": "other@example.com", "company_key": "n:otra"},
    ])
    conn = _conn(db_path)
    _attempt(conn, ids[0], "accepted")
    assert _emails(select_recipients(conn, CAMPAIGN, 1)) == ["other@example.com"]


def test_temporary_failure_at_company_does_not_exclude_colleague(contacts_db, db_path):
    ids = contacts_db([
        {"email": "failed@example.com", "company_key": "n:empresa"},
        {"email": "colleague@example.com", "company_key": "n:empresa"},
    ])
    conn = _conn(db_path)
    _attempt(conn, ids[0], "temporary_failure")
    assert _emails(select_recipients(conn, CAMPAIGN, 1)) == ["colleague@example.com"]


def test_company_emailed_in_other_campaign_is_excluded(contacts_db, db_path):
    ids = contacts_db([
        {"email": "sent@example.com", "company_key": "n:empresa", "times_contacted": 1,
         "last_contacted_at": "2026-09-14T13:01:00Z"},
        {"email": "colleague@example.com", "company_key": "n:empresa"},
        {"email": "other@example.com", "company_key": "n:otra"},
    ])
    conn = _conn(db_path)
    _attempt(conn, ids[0], "accepted", campaign="otra-campana")
    assert _emails(select_recipients(conn, CAMPAIGN, 1)) == ["other@example.com"]


def test_only_allowed_verification_statuses_are_selected(contacts_db, db_path):
    contacts_db([
        {"email": "valid@example.com", "company_key": "n:a"},
        {"email": "catch@example.com", "company_key": "n:b", "verification": "catch_all",
         "verified_at": "2026-09-15T00:00:00Z"},
        {"email": "invalid@example.com", "company_key": "n:c", "verification": "invalid",
         "verified_at": "2026-09-15T00:00:00Z"},
        {"email": "never@example.com", "company_key": "n:d", "verification": "unverified"},
    ])
    conn = _conn(db_path)
    selection = select_recipients(conn, CAMPAIGN, 1)
    assert _emails(selection) == ["valid@example.com"]
    assert (selection.eligible, selection.skipped_not_verified) == (1, 3)
    wider = select_recipients(conn, CAMPAIGN, 1, ("valid", "catch_all"))
    assert _emails(wider) == ["valid@example.com", "catch@example.com"]


def test_source_years_filter_and_unverified_opt_in(contacts_db, db_path):
    contacts_db([
        {"email": "new@example.com", "company_key": "n:a", "verification": "unverified"},
        {"email": "old@example.com", "company_key": "n:b", "verification": "unverified",
         "source_year": 2009, "source_file": "Year Book 2009.xlsx"},
        {"email": "bad@example.com", "company_key": "n:c", "verification": "invalid",
         "verified_at": "2026-09-15T00:00:00Z"},
    ])
    selection = select_recipients(_conn(db_path), CAMPAIGN, 1, ("valid", "unverified"), (2020,))
    assert _emails(selection) == ["new@example.com"]
    assert (selection.eligible, selection.skipped_not_verified) == (1, 1)


def test_invalid_best_contact_falls_back_to_verified_colleague(contacts_db, db_path):
    contacts_db([
        {"email": "best@example.com", "company_key": "n:empresa", "contact_name": "Ana",
         "verification": "invalid", "verified_at": "2026-09-15T00:00:00Z"},
        {"email": "colleague@example.com", "company_key": "n:empresa"},
    ])
    assert _emails(select_recipients(_conn(db_path), CAMPAIGN, 1)) == ["colleague@example.com"]


def test_verification_candidates(contacts_db, db_path):
    ids = contacts_db([
        {"email": "new@example.com", "company_key": "n:a", "verification": "unverified"},
        {"email": "done@example.com", "company_key": "n:b"},
        {"email": "bounced@example.com", "company_key": "n:c", "verification": "unverified",
         "bounced": 1, "bounced_at": "2026-09-14T00:00:00Z"},
        {"email": "generic@example.com", "company_key": "n:d", "verification": "unverified",
         "classification": "generic"},
        {"email": "sent@example.com", "company_key": "n:e", "verification": "unverified",
         "times_contacted": 1, "last_contacted_at": "2026-09-14T13:01:00Z"},
        {"email": "colleague@example.com", "company_key": "n:e", "verification": "unverified"},
        {"email": "second@example.com", "company_key": "n:a", "verification": "unverified"},
    ])
    conn = _conn(db_path)
    _attempt(conn, ids[4], "accepted", campaign="otra-campana")
    assert verification_candidates(conn) == ["new@example.com", "second@example.com"]


def test_one_per_company_tie_breaks(contacts_db, db_path):
    contacts_db([
        # completeness: company + city = 2
        {"email": "z-low@example.com", "company_key": "n:empresa", "source_row": 2},
        # completeness 3 (adds contact_name), year 2009
        {"email": "y-2009@example.com", "company_key": "n:empresa", "contact_name": "Ana",
         "source_year": 2009, "source_file": "Year Book 2009.xlsx", "source_row": 3},
        # completeness 3, year 2020, later row
        {"email": "b-2020-row9@example.com", "company_key": "n:empresa", "tax_id": "J123456789", "source_row": 9},
        # completeness 3, year 2020, earlier row → winner
        {"email": "c-2020-row5@example.com", "company_key": "n:empresa", "area": "Comercio", "source_row": 5},
    ])
    selection = select_recipients(_conn(db_path), CAMPAIGN, 1)
    assert _emails(selection) == ["c-2020-row5@example.com"]
    assert (selection.eligible, selection.skipped_same_company) == (4, 3)


def test_email_breaks_final_tie(contacts_db, db_path):
    contacts_db([
        {"email": "b@example.com", "company_key": "n:empresa", "source_row": 4},
        {"email": "a@example.com", "company_key": "n:empresa", "source_row": 4,
         "source_sheet": "Otra"},
    ])
    assert _emails(select_recipients(_conn(db_path), CAMPAIGN, 1)) == ["a@example.com"]


def test_2020_contacts_ordered_before_2009(contacts_db, db_path):
    contacts_db([
        {"email": "old1@example.com", "company_key": "n:a", "source_year": 2009, "source_file": "Year Book 2009.xlsx"},
        {"email": "new1@example.com", "company_key": "n:b"},
        {"email": "old2@example.com", "company_key": "n:c", "source_year": 2009, "source_file": "Year Book 2009.xlsx"},
        {"email": "new2@example.com", "company_key": "n:d"},
    ])
    assert _emails(select_recipients(_conn(db_path), CAMPAIGN, 1)) == [
        "new1@example.com", "new2@example.com", "old1@example.com", "old2@example.com",
    ]


def test_empty_database(db_path):
    selection = select_recipients(_conn(db_path), CAMPAIGN, 1)
    assert selection.recipients == [] and selection.eligible == 0
