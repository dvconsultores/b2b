from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from b2b.campaign import Campaign
from b2b.template import RenderedEmail


def write_preview(
    previews_dir: Path,
    campaign: Campaign,
    emails: Sequence[RenderedEmail],
    generated_at: datetime,
) -> Path:
    previews_dir.mkdir(parents=True, exist_ok=True)

    local = generated_at.astimezone(ZoneInfo(campaign.timezone))
    base = f"{campaign.name}-{local:%Y%m%d-%H%M%S}"
    path = previews_dir / f"{base}.txt"
    suffix = 2
    while path.exists():
        path = previews_dir / f"{base}-{suffix}.txt"
        suffix += 1

    n = len(emails)
    parts: list[str] = [
        f"Campaign: {campaign.name} (step {campaign.step})\n",
        f"Generated: {local:%Y-%m-%d %H:%M} {campaign.timezone}\n",
        f"Emails: {n}\n",
    ]
    for i, email in enumerate(emails, start=1):
        parts.append(
            f"\n===== {i} of {n} =====\n"
            f"To: {email.to}\n"
            f"Subject: {email.subject}\n"
            f"\n{email.body}"
        )

    path.write_text("".join(parts), encoding="utf-8")
    return path
