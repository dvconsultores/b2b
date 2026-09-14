"""Personal/generic classification of email addresses."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from b2b import ConfigError

_ROLE_WORD_RE = re.compile(r"^[a-z]+$")
_TRAILING_DIGITS_RE = re.compile(r"\d+$")


def load_role_words(path: Path) -> frozenset[str]:
    """Load role words from a UTF-8 file, one word per line."""
    words: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for n, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            word = line.lower()
            if not _ROLE_WORD_RE.match(word):
                raise ConfigError(
                    f"{path}: line {n}: role words must be letters only"
                )
            words.add(word)
    return frozenset(words)


def reduce_local_part(local: str) -> str:
    """Reduce a local part by removing trailing digits and separators."""
    reduced = _TRAILING_DIGITS_RE.sub("", local)
    for char in (".", "-", "_"):
        reduced = reduced.replace(char, "")
    return reduced


def classify(
    address: str, role_words: frozenset[str]
) -> Literal["personal", "generic"]:
    """Classify an address as generic (role) or personal."""
    local = address.rsplit("@", 1)[0]
    if reduce_local_part(local) in role_words:
        return "generic"
    return "personal"
