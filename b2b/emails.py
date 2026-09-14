from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EmailExtraction:
    candidates: list[str]
    invalid: list[tuple[str, str]]


_STRIP_CHARS = ".,;:<>()[]\"'"
_LOCAL_RE = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")


def normalize_token(token: str) -> str:
    cleaned = "".join(ch for ch in token if not ch.isspace())
    cleaned = cleaned.lower()
    if cleaned.startswith("mailto:"):
        cleaned = cleaned[len("mailto:"):]
    cleaned = cleaned.strip(_STRIP_CHARS)
    return cleaned


def validate(address: str) -> str | None:
    if not address:
        return "empty"
    if address.count("@") != 1:
        return "invalid_format"
    local, _, domain = address.partition("@")
    if not local or not domain:
        return "invalid_format"
    if not local.isascii():
        return "non_ascii_local_part"
    if len(local) > 64 or not _LOCAL_RE.match(local):
        return "invalid_format"
    if len(domain) > 253:
        return "invalid_format"
    labels = domain.split(".")
    if len(labels) < 2:
        return "invalid_format"
    for label in labels:
        if not label or len(label) > 63:
            return "invalid_format"
        if label.startswith("-") or label.endswith("-"):
            return "invalid_format"
        for ch in label:
            if not (ch.isalnum() or ch == "-"):
                return "invalid_format"
    tld = labels[-1]
    if len(tld) < 2 or not tld.isalpha():
        return "invalid_format"
    try:
        domain.encode("idna")
    except UnicodeError:
        return "invalid_format"
    return None


def extract(cell: str) -> EmailExtraction:
    candidates: list[str] = []
    invalid: list[tuple[str, str]] = []
    if cell.count("@") <= 1:
        token = normalize_token(cell)
        reason = validate(token)
        if reason is None:
            candidates.append(token)
        else:
            invalid.append((cell, reason))
        return EmailExtraction(candidates=candidates, invalid=invalid)
    seen: set[str] = set()
    for part in re.split(r"[;,/\s]+", cell):
        if "@" not in part:
            continue
        token = normalize_token(part)
        reason = validate(token)
        if reason is None:
            if token not in seen:
                seen.add(token)
                candidates.append(token)
        else:
            invalid.append((part, reason))
    return EmailExtraction(candidates=candidates, invalid=invalid)


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1]
