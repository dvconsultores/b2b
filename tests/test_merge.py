from b2b.merge import Candidate, completeness, group_candidates
from b2b.sources import SourceRow


def row(source_row, company="", contact_name="", city_raw="", tax_id_raw="", area="",
        source_file="ClientesFebrero2020.xls"):
    return SourceRow(
        source_file=source_file,
        source_sheet="Clientes",
        source_row=source_row,
        source_year=2020,
        company=company,
        contact_name=contact_name,
        city_raw=city_raw,
        tax_id_raw=tax_id_raw,
        area=area,
        email_raw="",
        company_contains_at=False,
    )


def cand(order, email, **fields):
    return Candidate(row=row(order + 2, **fields), email=email, order=order, company_key="n:x")


def test_completeness_counts_non_empty_fields():
    assert completeness(row(2)) == 0
    assert completeness(row(2, company="Ejemplo", city_raw="Caracas", area="  ")) == 2
    assert completeness(row(2, "A", "B", "C", "D", "E")) == 5


def test_most_complete_wins_and_earliest_breaks_ties():
    candidates = [
        cand(0, "ana@example.com", company="Ejemplo", city_raw="Caracas"),
        cand(1, "ana@example.com", company="Ejemplo", city_raw="Caracas", tax_id_raw="J123456789", area="Comercio"),
        cand(2, "ana@example.com", company="Ejemplo", city_raw="Caracas", tax_id_raw="J123456789", area="Industria"),
    ]
    [group] = group_candidates(candidates)
    assert group.winner.order == 1
    assert [c.order for c in group.merged] == [0, 2]


def test_groups_sorted_by_winner_order_and_input_order_ignored():
    candidates = [
        cand(3, "b@example.com", company="Dos"),
        cand(0, "a@example.com", company="Uno"),
        cand(1, "b@example.com", company="Dos", city_raw="Valencia"),
    ]
    groups = group_candidates(candidates)
    assert [g.winner.email for g in groups] == ["a@example.com", "b@example.com"]
    assert groups[1].winner.order == 1 and [c.order for c in groups[1].merged] == [3]


def test_single_candidate_group():
    [group] = group_candidates([cand(0, "a@example.com", company="Uno")])
    assert group.merged == [] and group.conflict is False


def test_conflict_on_company():
    [group] = group_candidates([
        cand(0, "a@example.com", company="Inversiones Uno, C.A."),
        cand(1, "a@example.com", company="Comercial Dos"),
    ])
    assert group.conflict is True


def test_conflict_on_city():
    [group] = group_candidates([
        cand(0, "a@example.com", city_raw="Caracas"),
        cand(1, "a@example.com", city_raw="Maracay"),
    ])
    assert group.conflict is True


def test_same_company_written_differently_is_not_a_conflict():
    [group] = group_candidates([
        cand(0, "a@example.com", company="INVERSIONES UNO, C.A.", city_raw="Mérida"),
        cand(1, "a@example.com", company="Inversiones Uno", city_raw="merida"),
    ])
    assert group.conflict is False


def test_empty_side_is_not_a_conflict():
    [group] = group_candidates([
        cand(0, "a@example.com", company="Uno", city_raw=""),
        cand(1, "a@example.com", company="", city_raw="Caracas"),
    ])
    assert group.conflict is False
