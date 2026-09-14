from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from b2b.campaign import load_campaign
from b2b.preview import write_preview
from b2b.template import RenderedEmail


def _campaign():
    return load_campaign(Path(__file__).resolve().parents[1] / "config" / "campaign.toml")


def _generated_at() -> datetime:
    return datetime(2026, 9, 14, 13, 5, 9, tzinfo=timezone.utc)


def test_golden_layout(tmp_path: Path) -> None:
    campaign = _campaign()
    emails = [
        RenderedEmail(
            contact_id=1,
            to="ana@example.com",
            subject="Hola Ana",
            body="Cuerpo uno.\n",
        ),
        RenderedEmail(
            contact_id=2,
            to="luis@example.com",
            subject="Hola Luis",
            body="Cuerpo dos.\n",
        ),
    ]

    path = write_preview(tmp_path, campaign, emails, _generated_at())

    assert path.name == "primer-contacto-2026-20260914-090509.txt"
    expected = (
        "Campaign: primer-contacto-2026 (step 1)\n"
        "Generated: 2026-09-14 09:05 America/Caracas\n"
        "Emails: 2\n"
        "\n"
        "===== 1 of 2 =====\n"
        "To: ana@example.com\n"
        "Subject: Hola Ana\n"
        "\n"
        "Cuerpo uno.\n"
        "\n"
        "===== 2 of 2 =====\n"
        "To: luis@example.com\n"
        "Subject: Hola Luis\n"
        "\n"
        "Cuerpo dos.\n"
    )
    assert path.read_text(encoding="utf-8") == expected


def test_name_collision_suffix(tmp_path: Path) -> None:
    campaign = _campaign()
    emails = [
        RenderedEmail(
            contact_id=1,
            to="ana@example.com",
            subject="Hola Ana",
            body="Cuerpo uno.\n",
        ),
    ]

    first = write_preview(tmp_path, campaign, emails, _generated_at())
    second = write_preview(tmp_path, campaign, emails, _generated_at())

    assert first.name == "primer-contacto-2026-20260914-090509.txt"
    assert second.name == "primer-contacto-2026-20260914-090509-2.txt"
    assert second.parent == tmp_path


def test_zero_emails_writes_header_only(tmp_path: Path) -> None:
    campaign = _campaign()

    path = write_preview(tmp_path, campaign, [], _generated_at())

    content = path.read_text(encoding="utf-8")
    assert content == (
        "Campaign: primer-contacto-2026 (step 1)\n"
        "Generated: 2026-09-14 09:05 America/Caracas\n"
        "Emails: 0\n"
    )
    assert "=====" not in content


def test_creates_previews_dir(tmp_path: Path) -> None:
    campaign = _campaign()
    previews_dir = tmp_path / "nested" / "previews"
    assert not previews_dir.exists()

    path = write_preview(previews_dir, campaign, [], _generated_at())

    assert previews_dir.is_dir()
    assert path.parent == previews_dir
