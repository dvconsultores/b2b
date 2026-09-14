"""Tests for send window, cap and interval rules (spec 002 plan D7, D11)."""
import random
from datetime import date, datetime, time, timezone
from types import SimpleNamespace

from b2b import pacing


def campaign(**overrides):
    base = dict(
        timezone="America/Caracas",
        send_days=("mon", "tue", "wed", "thu", "fri"),
        send_start=time(8, 0),
        send_end=time(17, 0),
        hourly_cap=20,
        launch_price_end=date(2026, 12, 31),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# Caracas is UTC-4 all year.

def test_local_now_converts_to_campaign_zone():
    local = pacing.local_now(campaign(), utc(2026, 9, 14, 13, 0))
    assert (local.hour, local.minute, local.utcoffset().total_seconds()) == (9, 0, -4 * 3600)


def test_window_edges():
    c = campaign()
    assert pacing.window_contains(c, utc(2026, 9, 18, 20, 59))       # Friday 16:59
    assert not pacing.window_contains(c, utc(2026, 9, 18, 21, 0))    # Friday 17:00
    assert pacing.window_contains(c, utc(2026, 9, 14, 12, 0))        # Monday 08:00
    assert not pacing.window_contains(c, utc(2026, 9, 14, 11, 59))   # Monday 07:59
    assert not pacing.window_contains(c, utc(2026, 9, 19, 14, 0))    # Saturday 10:00


def test_next_window_start():
    c = campaign()
    assert pacing.next_window_start(c, utc(2026, 9, 18, 21, 0)) == utc(2026, 9, 21, 12, 0)   # Fri 17:00 → Mon 08:00
    assert pacing.next_window_start(c, utc(2026, 9, 19, 14, 0)) == utc(2026, 9, 21, 12, 0)   # Sat → Mon
    assert pacing.next_window_start(c, utc(2026, 9, 14, 11, 0)) == utc(2026, 9, 14, 12, 0)   # Mon 07:00 → 08:00
    inside = utc(2026, 9, 15, 15, 30)
    assert pacing.next_window_start(c, inside) == inside


def test_next_window_start_weekend_only_campaign():
    c = campaign(send_days=("sat",))
    assert pacing.next_window_start(c, utc(2026, 9, 19, 21, 0)) == utc(2026, 9, 26, 12, 0)  # Sat 17:00 → next Sat


def test_next_interval_bounds():
    c = campaign(hourly_cap=20)
    rng = random.Random(7)
    values = [pacing.next_interval(c, rng) for _ in range(500)]
    assert min(values) >= 144 and max(values) <= 216
    assert max(values) - min(values) > 50


def test_cap_wait_seconds():
    now = utc(2026, 9, 14, 13, 0)
    assert pacing.cap_wait_seconds(19, "2026-09-14T12:30:00Z", 20, now) == 0
    assert pacing.cap_wait_seconds(20, "2026-09-14T12:30:00Z", 20, now) == 1800
    assert pacing.cap_wait_seconds(25, "2026-09-14T11:00:00Z", 20, now) == 0
    assert pacing.cap_wait_seconds(20, None, 20, now) == 0


def test_launch_price_passed_uses_local_date():
    c = campaign()
    assert not pacing.launch_price_passed(c, utc(2027, 1, 1, 3, 59))  # 2026-12-31 23:59 local
    assert pacing.launch_price_passed(c, utc(2027, 1, 1, 4, 0))       # 2027-01-01 00:00 local
