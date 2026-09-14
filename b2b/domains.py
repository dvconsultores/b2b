"""Check that address domains accept mail, using DNS lookups of the domain only (plan D5)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Literal

import dns.exception
import dns.resolver

DomainStatus = Literal["accepts", "domain_not_found", "no_mail_server", "null_mx", "unverified"]

REJECT_STATUSES: frozenset[str] = frozenset({"domain_not_found", "no_mail_server", "null_mx"})


def _is_null_mx(record) -> bool:
    return record.preference == 0 and record.exchange.to_text() == "."


def _check_address_records(resolver, name: str) -> DomainStatus:
    # No MX: RFC 5321 implicit MX — the domain's own A/AAAA record receives mail.
    for rdtype in ("A", "AAAA"):
        try:
            resolver.resolve(name, rdtype)
        except dns.resolver.NoAnswer:
            continue
        except dns.resolver.NXDOMAIN:
            return "domain_not_found"
        except dns.exception.DNSException:
            return "unverified"
        return "accepts"
    return "no_mail_server"


def make_dns_checker(
    timeout: float = 3.0, resolver: object | None = None
) -> Callable[[str], DomainStatus]:
    if resolver is None:
        resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout

    def check(domain: str) -> DomainStatus:
        try:
            name = domain.encode("idna").decode("ascii")
        except UnicodeError:
            return "unverified"
        try:
            answer = resolver.resolve(name, "MX")
        except dns.resolver.NXDOMAIN:
            return "domain_not_found"
        except dns.resolver.NoAnswer:
            return _check_address_records(resolver, name)
        except dns.exception.DNSException:
            return "unverified"
        records = list(answer)
        if records and all(_is_null_mx(record) for record in records):
            return "null_mx"
        return "accepts"

    return check


def check_domains(
    domains: Iterable[str], checker: Callable[[str], DomainStatus], workers: int = 16
) -> dict[str, DomainStatus]:
    unique = sorted(set(domains))

    def safe_check(domain: str) -> DomainStatus:
        try:
            return checker(domain)
        except Exception:
            return "unverified"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = list(pool.map(safe_check, unique))
    return dict(zip(unique, statuses))
