from dataclasses import dataclass

import dns.exception
import dns.name
import dns.resolver
import pytest

from b2b.domains import REJECT_STATUSES, check_domains, make_dns_checker


@dataclass
class FakeMX:
    preference: int
    exchange: dns.name.Name


def mx(host: str, preference: int = 10) -> FakeMX:
    return FakeMX(preference, dns.name.from_text(host))


NULL_MX = FakeMX(0, dns.name.root)


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


def status(script, domain="example.com"):
    resolver = FakeResolver(script)
    return make_dns_checker(timeout=2.5, resolver=resolver)(domain), resolver


def test_mx_answer_accepts():
    result, resolver = status({("example.com", "MX"): [mx("mail.example.com.")]})
    assert result == "accepts"
    assert resolver.calls == [("example.com", "MX")]
    assert resolver.lifetime == 2.5


def test_null_mx_rejects():
    result, _ = status({("example.com", "MX"): [NULL_MX]})
    assert result == "null_mx"


def test_null_mx_mixed_with_real_mx_accepts():
    result, _ = status({("example.com", "MX"): [NULL_MX, mx("mail.example.com.")]})
    assert result == "accepts"


def test_nxdomain_on_mx():
    result, _ = status({("example.com", "MX"): dns.resolver.NXDOMAIN})
    assert result == "domain_not_found"


def test_no_mx_falls_back_to_a():
    result, resolver = status({
        ("example.com", "MX"): dns.resolver.NoAnswer,
        ("example.com", "A"): ["192.0.2.1"],
    })
    assert result == "accepts"
    assert resolver.calls == [("example.com", "MX"), ("example.com", "A")]


def test_no_mx_no_a_falls_back_to_aaaa():
    result, _ = status({
        ("example.com", "MX"): dns.resolver.NoAnswer,
        ("example.com", "A"): dns.resolver.NoAnswer,
        ("example.com", "AAAA"): ["2001:db8::1"],
    })
    assert result == "accepts"


def test_no_records_at_all():
    result, _ = status({
        ("example.com", "MX"): dns.resolver.NoAnswer,
        ("example.com", "A"): dns.resolver.NoAnswer,
        ("example.com", "AAAA"): dns.resolver.NoAnswer,
    })
    assert result == "no_mail_server"


def test_nxdomain_during_fallback():
    result, _ = status({
        ("example.com", "MX"): dns.resolver.NoAnswer,
        ("example.com", "A"): dns.resolver.NXDOMAIN,
    })
    assert result == "domain_not_found"


@pytest.mark.parametrize("error", [dns.exception.Timeout, dns.resolver.NoNameservers])
def test_lookup_failure_on_mx_is_unverified(error):
    result, _ = status({("example.com", "MX"): error})
    assert result == "unverified"


def test_timeout_during_fallback_is_unverified():
    result, _ = status({
        ("example.com", "MX"): dns.resolver.NoAnswer,
        ("example.com", "A"): dns.exception.Timeout,
    })
    assert result == "unverified"


def test_unicode_domain_is_queried_as_idna():
    domain = "compañía.example"
    ascii_name = domain.encode("idna").decode("ascii")
    result, resolver = status({(ascii_name, "MX"): [mx("mail.example.")]}, domain)
    assert result == "accepts"
    assert resolver.calls == [(ascii_name, "MX")]


def test_reject_statuses():
    assert REJECT_STATUSES == {"domain_not_found", "no_mail_server", "null_mx"}


def test_check_domains_dedupes_sorts_and_maps_errors():
    seen = []

    def checker(domain):
        seen.append(domain)
        if domain == "broken.example":
            raise ValueError("unexpected")
        return "accepts" if domain == "a.example" else "null_mx"

    result = check_domains(["b.example", "a.example", "b.example", "broken.example"], checker, workers=2)
    assert list(result) == ["a.example", "b.example", "broken.example"]
    assert result == {"a.example": "accepts", "b.example": "null_mx", "broken.example": "unverified"}
    assert sorted(seen) == ["a.example", "b.example", "broken.example"]


def test_check_domains_empty():
    assert check_domains([], lambda d: "accepts") == {}


def test_default_resolver_never_reaches_network_in_tests():
    # conftest disables dns.resolver.Resolver.resolve; the failure must surface as unverified.
    result = check_domains(["example.com"], make_dns_checker(timeout=0.5))
    assert result == {"example.com": "unverified"}
