"""City normalization and mapping (plan D8)."""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from b2b import ConfigError
from b2b.reports import ReviewItem, SourceRef

_LOWERCASE_PARTICLES = {"de", "del", "la", "las", "los", "y"}


@dataclass(frozen=True)
class CityMap:
    canonical_by_key: dict[str, str]


def match_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = without_marks.casefold()
    spaced = re.sub(r"[^\w\s]", " ", folded)
    return " ".join(spaced.split())


def title_case(value: str) -> str:
    words = value.split(" ")
    result = []
    for index, word in enumerate(words):
        if not word:
            result.append(word)
            continue
        lowered = word[:1].upper() + word[1:].lower()
        if index > 0 and word.lower() in _LOWERCASE_PARTICLES:
            lowered = word.lower()
        result.append(lowered)
    return " ".join(result)


def load_city_map(path: Path) -> CityMap:
    canonical_by_key: dict[str, str] = {}
    line_by_key: dict[str, int] = {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ConfigError(f"{path}: expected header 'variant,canonical'")
        if header != ["variant", "canonical"]:
            raise ConfigError(f"{path}: expected header 'variant,canonical'")
        for line_number, row in enumerate(reader, start=2):
            if len(row) != 2 or not row[0].strip() or not row[1].strip():
                raise ConfigError(
                    f"{path}: line {line_number}: expected variant,canonical"
                )
            variant, canonical = row[0], row[1]
            key = match_key(variant)
            if key in canonical_by_key and canonical_by_key[key] != canonical:
                raise ConfigError(
                    f"{path}: lines {line_by_key[key]} and {line_number}: "
                    "conflicting canonical names"
                )
            canonical_by_key[key] = canonical
            line_by_key[key] = line_number
    return CityMap(canonical_by_key=canonical_by_key)


def normalize_city(raw: str, city_map: CityMap) -> tuple[str, bool]:
    stripped = raw.strip()
    if not stripped:
        return ("", False)
    key = match_key(raw)
    if key in city_map.canonical_by_key:
        return (city_map.canonical_by_key[key], False)
    return (title_case(" ".join(raw.split())), True)


def aggregate_unmapped_cities(raw_values: Iterable[str]) -> list[ReviewItem]:
    groups: dict[str, list[str]] = {}
    for value in raw_values:
        if not value.strip():
            continue
        key = match_key(value)
        groups.setdefault(key, []).append(value)
    items = [
        ReviewItem(
            type="city_not_in_mapping",
            ref=SourceRef(),
            detail=values[0],
            count=len(values),
        )
        for values in groups.values()
    ]
    items.sort(key=lambda item: item.detail.casefold())
    return items
