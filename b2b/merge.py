"""Group address candidates and pick the record that represents each contact (plan D9)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from b2b.cities import match_key
from b2b.companies import name_key
from b2b.sources import SourceRow


@dataclass(frozen=True)
class Candidate:
    row: SourceRow
    email: str
    order: int
    company_key: str


@dataclass(frozen=True)
class Group:
    winner: Candidate
    merged: list[Candidate]
    conflict: bool


def completeness(row: SourceRow) -> int:
    fields = (row.company, row.contact_name, row.city_raw, row.tax_id_raw, row.area)
    return sum(1 for value in fields if value.strip())


def group_candidates(candidates: Sequence[Candidate]) -> list[Group]:
    by_email: dict[str, list[Candidate]] = {}
    for candidate in sorted(candidates, key=lambda c: c.order):
        by_email.setdefault(candidate.email, []).append(candidate)

    groups = []
    for members in by_email.values():
        # Highest completeness wins; members are in order, so max() keeps the earliest on ties.
        winner = max(members, key=completeness_of)
        merged = [member for member in members if member.order != winner.order]
        company_keys = {name_key(member.row.company) for member in members} - {""}
        city_keys = {match_key(member.row.city_raw) for member in members} - {""}
        conflict = len(company_keys) > 1 or len(city_keys) > 1
        groups.append(Group(winner=winner, merged=merged, conflict=conflict))
    return sorted(groups, key=lambda group: group.winner.order)


def completeness_of(candidate: Candidate) -> int:
    return completeness(candidate.row)
