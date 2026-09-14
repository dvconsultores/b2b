from __future__ import annotations

from b2b.send_report import SendSummary, format_send_summary


def test_format_send_summary_golden():
    summary = SendSummary(
        mode="send",
        result="done",
        campaign="primer-contacto-2026",
        step=1,
        eligible=120,
        skipped_same_company=7,
        skipped_rendered_link=3,
        selected=110,
        previewed=110,
        test_sent=2,
        accepted=98,
        permanent_rejections=4,
        temporary_failures=5,
        unknown=1,
        bounced=1,
        bounce_base=40,
        dmarc="pass",
        spf="pass",
        forced_no_dmarc=False,
        stop_reason="-",
        next_window="2026-03-02 09:00 CET",
        preview_path="out/preview-2026-03-01.txt",
    )

    expected = (
        "send_first_email: send done\n"
        "campaign: primer-contacto-2026 (step 1)\n"
        "  eligible contacts:" + " " * 8 + "120\n"
        "  skipped same company:" + " " * 5 + "7\n"
        "  skipped rendered link:" + " " * 4 + "3\n"
        "  selected:" + " " * 17 + "110\n"
        "  previewed:" + " " * 16 + "110\n"
        "  test emails sent:" + " " * 9 + "2\n"
        "  accepted:" + " " * 17 + "98\n"
        "  permanent rejections:" + " " * 5 + "4\n"
        "  temporary failures:" + " " * 7 + "5\n"
        "  unknown outcome:" + " " * 10 + "1\n"
        "  campaign bounce rate:" + " " * 5 + "2.5% (1 of 40)\n"
        "  DMARC:" + " " * 20 + "pass\n"
        "  SPF:" + " " * 22 + "pass\n"
        "  forced no DMARC:" + " " * 10 + "no\n"
        "  stop reason:" + " " * 14 + "-\n"
        "  next window opens:" + " " * 8 + "2026-03-02 09:00 CET\n"
        "preview: out/preview-2026-03-01.txt\n"
    )

    assert format_send_summary(summary) == expected


def test_format_send_summary_zero_bounce_base():
    summary = SendSummary(mode="preview", result="nothing_to_send", campaign="c", step=2)

    result = format_send_summary(summary)

    assert "  campaign bounce rate:" + " " * 5 + "0.0% (0 of 0)\n" in result


def test_format_send_summary_trailing_newline():
    summary = SendSummary(mode="send", result="done", campaign="c", step=1)

    result = format_send_summary(summary)

    assert result.endswith("\n")
    assert not result.endswith("\n\n")
