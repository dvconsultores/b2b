from dataclasses import dataclass

import dns.exception
import dns.resolver
import pytest

from b2b.preflight import PreflightResult, check_sender_domain, make_resolver


@dataclass
class FakeTXT:
    strings: tuple[bytes, ...]


def txt(*parts: bytes) -> FakeTXT:
    return FakeTXT(tuple(parts))


class FakeResolver:
    def __init__(self, script: dict[tuple[str, str], object]):
        self.script = script
        self.calls: list[tuple[str, str]] = []
        self.lifetime = None

    def resolve(self, name, rdtype):
        self.calls.append((name, rdtype))
        outcome = self.script[(name, rdtype)]
        if isinstance(outcome, type) and issubclass(outcome, BaseException):
            raise outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def run(script, domain="example.com"):
    resolver = FakeResolver(script)
    return check_sender_domain(domain, resolver), resolver


def test_make_resolver_sets_lifetime():
    resolver = make_resolver(timeout=2.5)
    assert resolver.lifetime == 2.5


def test_dmarc_present_with_p_none():
    result, resolver = run(
        {
            ("_dmarc.example.com", "TXT"): [txt(b"v=DMARC1; p=none; rua=mailto:x@example.com")],
            ("example.com", "TXT"): [txt(b"v=spf1 include:amazonses.com ~all")],
        }
    )
    assert result == PreflightResult(dmarc="present", dmarc_policy="none", spf="includes_ses")
    assert resolver.calls == [("_dmarc.example.com", "TXT"), ("example.com", "TXT")]


def test_dmarc_present_with_p_reject():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): [txt(b"v=DMARC1; p=reject")],
            ("example.com", "TXT"): [txt(b"v=spf1 include:amazonses.com ~all")],
        }
    )
    assert result.dmarc == "present"
    assert result.dmarc_policy == "reject"


def test_dmarc_missing_via_nxdomain():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): dns.resolver.NXDOMAIN,
            ("example.com", "TXT"): [txt(b"v=spf1 include:amazonses.com ~all")],
        }
    )
    assert result.dmarc == "missing"
    assert result.dmarc_policy is None


def test_dmarc_missing_via_non_dmarc_txt_only():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): [txt(b"some-other-record")],
            ("example.com", "TXT"): [txt(b"v=spf1 include:amazonses.com ~all")],
        }
    )
    assert result.dmarc == "missing"
    assert result.dmarc_policy is None


def test_dmarc_unverified_via_timeout():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): dns.exception.Timeout,
            ("example.com", "TXT"): [txt(b"v=spf1 include:amazonses.com ~all")],
        }
    )
    assert result.dmarc == "unverified"
    assert result.dmarc_policy is None


def test_spf_includes_ses():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): [txt(b"v=DMARC1; p=none")],
            ("example.com", "TXT"): [txt(b"v=spf1 include:amazonses.com ~all")],
        }
    )
    assert result.spf == "includes_ses"


def test_spf_present_without_ses():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): [txt(b"v=DMARC1; p=none")],
            ("example.com", "TXT"): [txt(b"v=spf1 include:other.example ~all")],
        }
    )
    assert result.spf == "present_without_ses"


def test_spf_missing():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): [txt(b"v=DMARC1; p=none")],
            ("example.com", "TXT"): dns.resolver.NoAnswer,
        }
    )
    assert result.spf == "missing"


def test_spf_unverified():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): [txt(b"v=DMARC1; p=none")],
            ("example.com", "TXT"): dns.exception.Timeout,
        }
    )
    assert result.spf == "unverified"


def test_multi_string_txt_record_joined():
    result, _ = run(
        {
            ("_dmarc.example.com", "TXT"): [txt(b"v=DMARC1; p=", b"reject")],
            ("example.com", "TXT"): [txt(b"v=spf1 include:", b"amazonses.com ~all")],
        }
    )
    assert result.dmarc == "present"
    assert result.dmarc_policy == "reject"
    assert result.spf == "includes_ses"


def test_unicode_domain_is_queried_as_idna():
    domain = "compañía.example"
    ascii_name = domain.encode("idna").decode("ascii")
    result, resolver = run(
        {
            (f"_dmarc.{ascii_name}", "TXT"): [txt(b"v=DMARC1; p=none")],
            (ascii_name, "TXT"): [txt(b"v=spf1 include:amazonses.com ~all")],
        },
        domain,
    )
    assert result.dmarc == "present"
    assert resolver.calls == [(f"_dmarc.{ascii_name}", "TXT"), (ascii_name, "TXT")]
