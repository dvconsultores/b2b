"""Deliverability preflight: check sender domain DMARC and SPF records (plan D14)."""
from __future__ import annotations

from dataclasses import dataclass

import dns.exception
import dns.resolver


@dataclass(frozen=True)
class PreflightResult:
    dmarc: str                 # "present" | "missing" | "unverified"
    dmarc_policy: str | None
    spf: str                   # "includes_ses" | "present_without_ses" | "missing" | "unverified"


def make_resolver(timeout: float = 5.0) -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout
    return resolver


def _txt_strings(record) -> str:
    return b"".join(record.strings).decode("utf-8", "replace")


def _check_dmarc(name: str, resolver: object) -> tuple[str, str | None]:
    try:
        answer = resolver.resolve(f"_dmarc.{name}", "TXT")
    except dns.resolver.NXDOMAIN:
        return "missing", None
    except dns.resolver.NoAnswer:
        return "missing", None
    except dns.exception.DNSException:
        return "unverified", None
    for record in answer:
        text = _txt_strings(record)
        if text.lower().startswith("v=dmarc1"):
            policy = None
            for tag in text.split(";"):
                tag = tag.strip()
                if "=" in tag:
                    key, _, value = tag.partition("=")
                    if key.strip().lower() == "p":
                        policy = value.strip()
            return "present", policy
    return "missing", None


def _check_spf(name: str, resolver: object) -> str:
    try:
        answer = resolver.resolve(name, "TXT")
    except dns.resolver.NXDOMAIN:
        return "missing"
    except dns.resolver.NoAnswer:
        return "missing"
    except dns.exception.DNSException:
        return "unverified"
    for record in answer:
        text = _txt_strings(record)
        if text.lower().startswith("v=spf1"):
            if "include:amazonses.com" in text.lower():
                return "includes_ses"
            return "present_without_ses"
    return "missing"


def check_sender_domain(domain: str, resolver: object) -> PreflightResult:
    try:
        name = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return PreflightResult(dmarc="unverified", dmarc_policy=None, spf="unverified")
    dmarc, dmarc_policy = _check_dmarc(name, resolver)
    spf = _check_spf(name, resolver)
    return PreflightResult(dmarc=dmarc, dmarc_policy=dmarc_policy, spf=spf)
