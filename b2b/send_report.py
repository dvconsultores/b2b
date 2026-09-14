from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SendSummary:
    mode: str
    result: str
    campaign: str
    step: int
    eligible: int = 0
    skipped_same_company: int = 0
    skipped_rendered_link: int = 0
    selected: int = 0
    previewed: int = 0
    test_sent: int = 0
    accepted: int = 0
    permanent_rejections: int = 0
    temporary_failures: int = 0
    unknown: int = 0
    bounced: int = 0
    bounce_base: int = 0
    dmarc: str = "-"
    spf: str = "-"
    forced_no_dmarc: bool = False
    stop_reason: str = "-"
    next_window: str = "-"
    preview_path: str = "-"


def format_send_summary(summary: SendSummary) -> str:
    bounce_rate = (
        f"{(summary.bounced / summary.bounce_base * 100) if summary.bounce_base else 0:.1f}%"
        f" ({summary.bounced} of {summary.bounce_base})"
    )
    lines = [
        f"send_first_email: {summary.mode} {summary.result}",
        f"campaign: {summary.campaign} (step {summary.step})",
        "  " + f"{'eligible contacts:':<26}" + str(summary.eligible),
        "  " + f"{'skipped same company:':<26}" + str(summary.skipped_same_company),
        "  " + f"{'skipped rendered link:':<26}" + str(summary.skipped_rendered_link),
        "  " + f"{'selected:':<26}" + str(summary.selected),
        "  " + f"{'previewed:':<26}" + str(summary.previewed),
        "  " + f"{'test emails sent:':<26}" + str(summary.test_sent),
        "  " + f"{'accepted:':<26}" + str(summary.accepted),
        "  " + f"{'permanent rejections:':<26}" + str(summary.permanent_rejections),
        "  " + f"{'temporary failures:':<26}" + str(summary.temporary_failures),
        "  " + f"{'unknown outcome:':<26}" + str(summary.unknown),
        "  " + f"{'campaign bounce rate:':<26}" + bounce_rate,
        "  " + f"{'DMARC:':<26}" + summary.dmarc,
        "  " + f"{'SPF:':<26}" + summary.spf,
        "  " + f"{'forced no DMARC:':<26}" + ("yes" if summary.forced_no_dmarc else "no"),
        "  " + f"{'stop reason:':<26}" + summary.stop_reason,
        "  " + f"{'next window opens:':<26}" + summary.next_window,
        f"preview: {summary.preview_path}",
    ]
    return "\n".join(lines) + "\n"
