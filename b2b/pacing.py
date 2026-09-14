"""Send window, rolling hourly cap and send intervals (spec 002 plan D7, D11)."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from b2b.campaign import Campaign

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def local_now(campaign: Campaign, moment: datetime) -> datetime:
    return moment.astimezone(ZoneInfo(campaign.timezone))


def window_contains(campaign: Campaign, moment: datetime) -> bool:
    local = local_now(campaign, moment)
    return (
        _DAYS[local.weekday()] in campaign.send_days
        and campaign.send_start <= local.time() < campaign.send_end
    )


def next_window_start(campaign: Campaign, moment: datetime) -> datetime:
    """Earliest moment at or after `moment` inside the send window, in UTC."""
    if window_contains(campaign, moment):
        return moment.astimezone(timezone.utc)
    zone = ZoneInfo(campaign.timezone)
    local = local_now(campaign, moment)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if _DAYS[day.weekday()] not in campaign.send_days:
            continue
        start = datetime.combine(day, campaign.send_start, tzinfo=zone)
        if start >= local:
            return start.astimezone(timezone.utc)
    raise ValueError("send_days is empty")


def next_interval(campaign: Campaign, rng: random.Random) -> float:
    return 3600 / campaign.hourly_cap * rng.uniform(0.8, 1.2)


def cap_wait_seconds(count: int, oldest_created_at: str | None, hourly_cap: int, now: datetime) -> float:
    if count < hourly_cap or oldest_created_at is None:
        return 0.0
    oldest = datetime.strptime(oldest_created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return max(0.0, (oldest + timedelta(seconds=3600) - now).total_seconds())


def launch_price_passed(campaign: Campaign, moment: datetime) -> bool:
    return local_now(campaign, moment).date() > campaign.launch_price_end
