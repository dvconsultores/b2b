"""Company key assignment for the clean contact list (spec 001, plan D7).

Pure functions only: no I/O, no dependencies beyond the standard library.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence

_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("c", "a"),
    ("ca",),
    ("s", "a"),
    ("sa",),
    ("s", "r", "l"),
    ("srl",),
    ("compania", "anonima"),
    ("sociedad", "anonima"),
)

_RIF_RE = re.compile(r"[VEJPG]\d{8,9}")


def name_key(company: str) -> str:
    """Return the grouping key for a company name (plan D7)."""
    if not company:
        return ""
    text = unicodedata.normalize("NFKD", company)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^0-9a-z]+", " ", text)
    tokens = text.split()
    while tokens:
        stripped = False
        for suffix in _SUFFIXES:
            n = len(suffix)
            if len(tokens) > n and tuple(tokens[-n:]) == suffix:
                tokens = tokens[:-n]
                stripped = True
                break
        if not stripped:
            break
    result = " ".join(tokens)
    if not result:
        return company.strip().casefold()
    return result


def normalize_tax_id(raw: str) -> str:
    """Uppercase and keep only [0-9A-Z] characters."""
    return re.sub(r"[^0-9A-Z]", "", raw.upper())


def is_valid_rif(normalized: str) -> bool:
    """True when the normalized tax id matches the RIF shape."""
    return _RIF_RE.fullmatch(normalized) is not None


def stored_tax_id(raw: str) -> str:
    """Normalized tax id when valid, otherwise the trimmed raw value."""
    normalized = normalize_tax_id(raw)
    if is_valid_rif(normalized):
        return normalized
    return raw.strip()


def assign_company_keys(items: Sequence[tuple[str, str, str]]) -> list[str]:
    """Assign a shared company key to each item (plan D7).

    ``items`` is a sequence of ``(company, tax_id_raw, email)`` tuples.
    Returns a list of keys in the same order as ``items``.
    """
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    name_keys = [name_key(company) for company, _, _ in items]
    rifs = [normalize_tax_id(raw) for _, raw, _ in items]

    by_name: dict[str, int] = {}
    for i, key in enumerate(name_keys):
        if key:
            if key in by_name:
                union(by_name[key], i)
            else:
                by_name[key] = i

    by_rif: dict[str, int] = {}
    for i, rif in enumerate(rifs):
        if is_valid_rif(rif):
            if rif in by_rif:
                union(by_rif[rif], i)
            else:
                by_rif[rif] = i

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)

    keys = [""] * n
    for members in components.values():
        members.sort()
        chosen = None
        for i in members:
            if name_keys[i]:
                chosen = "n:" + name_keys[i]
                break
        if chosen is None:
            for i in members:
                if is_valid_rif(rifs[i]):
                    chosen = "t:" + rifs[i]
                    break
        if chosen is None:
            chosen = "e:" + items[members[0]][2]
        for i in members:
            keys[i] = chosen
    return keys
