"""Tests for b2b.cities (plan D8)."""
from __future__ import annotations

from pathlib import Path

import pytest

from b2b import ConfigError
from b2b.cities import (
    CityMap,
    aggregate_unmapped_cities,
    load_city_map,
    match_key,
    normalize_city,
    title_case,
)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cities.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_match_key_ignores_accents_case_punctuation():
    assert match_key("Mérida") == match_key("MERIDA")
    assert match_key("San Cristóbal") == match_key("san-cristobal")
    assert match_key("  San   Cristobal  ") == "san cristobal"


def test_title_case_particles():
    assert title_case("San Juan de los Morros") == "San Juan de los Morros"
    assert title_case("Villa Inventada") == "Villa Inventada"
    assert title_case("De la Cruz") == "De la Cruz"


def test_normalize_city_mapped_variants(tmp_path):
    path = _write(
        tmp_path,
        "variant,canonical\n"
        "merida,Mérida\n"
        "san cristobal,San Cristóbal\n",
    )
    city_map = load_city_map(path)
    assert normalize_city("MERIDA", city_map) == ("Mérida", False)
    assert normalize_city("Mérida", city_map) == ("Mérida", False)
    assert normalize_city("  merida  ", city_map) == ("Mérida", False)
    assert normalize_city("San-Cristobal", city_map) == ("San Cristóbal", False)


def test_normalize_city_unmapped_title_cases(tmp_path):
    path = _write(tmp_path, "variant,canonical\nmerida,Mérida\n")
    city_map = load_city_map(path)
    assert normalize_city("SAN JUAN DE LOS MORROS", city_map) == (
        "San Juan de los Morros",
        True,
    )


def test_normalize_city_empty(tmp_path):
    path = _write(tmp_path, "variant,canonical\nmerida,Mérida\n")
    city_map = load_city_map(path)
    assert normalize_city("", city_map) == ("", False)
    assert normalize_city("   ", city_map) == ("", False)


def test_load_city_map_wrong_header(tmp_path):
    path = _write(tmp_path, "name,city\nmerida,Mérida\n")
    with pytest.raises(ConfigError) as excinfo:
        load_city_map(path)
    assert str(excinfo.value) == f"{path}: expected header 'variant,canonical'"


def test_load_city_map_missing_header(tmp_path):
    path = _write(tmp_path, "")
    with pytest.raises(ConfigError) as excinfo:
        load_city_map(path)
    assert str(excinfo.value) == f"{path}: expected header 'variant,canonical'"


def test_load_city_map_bad_row(tmp_path):
    path = _write(tmp_path, "variant,canonical\nmerida\n")
    with pytest.raises(ConfigError) as excinfo:
        load_city_map(path)
    assert str(excinfo.value) == f"{path}: line 2: expected variant,canonical"


def test_load_city_map_empty_field(tmp_path):
    path = _write(tmp_path, "variant,canonical\nmerida,\n")
    with pytest.raises(ConfigError) as excinfo:
        load_city_map(path)
    assert str(excinfo.value) == f"{path}: line 2: expected variant,canonical"


def test_load_city_map_conflicting_canonical(tmp_path):
    path = _write(
        tmp_path,
        "variant,canonical\n"
        "merida,Mérida\n"
        "MERIDA,Mérida City\n",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_city_map(path)
    assert str(excinfo.value) == (
        f"{path}: lines 2 and 3: conflicting canonical names"
    )


def test_load_city_map_duplicate_same_canonical_ok(tmp_path):
    path = _write(
        tmp_path,
        "variant,canonical\n"
        "merida,Mérida\n"
        "MERIDA,Mérida\n",
    )
    city_map = load_city_map(path)
    assert city_map.canonical_by_key[match_key("merida")] == "Mérida"


def test_aggregate_unmapped_cities_counts_and_order():
    values = [
        "Villa Inventada",
        "VILLA INVENTADA",
        "Otra Ciudad",
        "",
        "   ",
        "otra-ciudad",
    ]
    items = aggregate_unmapped_cities(values)
    assert [item.detail for item in items] == ["Otra Ciudad", "Villa Inventada"]
    assert [item.count for item in items] == [2, 2]
    assert all(item.type == "city_not_in_mapping" for item in items)


def test_aggregate_unmapped_cities_sorted_by_casefold():
    values = ["zeta", "Alpha", "beta"]
    items = aggregate_unmapped_cities(values)
    assert [item.detail for item in items] == ["Alpha", "beta", "zeta"]


def test_real_config_cities_merida():
    path = Path(__file__).resolve().parents[1] / "config" / "cities.csv"
    city_map = load_city_map(path)
    assert normalize_city("MERIDA", city_map) == ("Mérida", False)
