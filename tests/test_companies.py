"""Tests for b2b.companies (spec 001, plan D7, task T012)."""

from __future__ import annotations

from b2b.companies import (
    assign_company_keys,
    is_valid_rif,
    name_key,
    normalize_tax_id,
    stored_tax_id,
)


def test_name_key_variants_share_key():
    a = name_key("INVERSIONES EJEMPLO, C.A.")
    b = name_key("Inversiones Ejemplo C A")
    c = name_key("inversiones  ejemplo")
    assert a == b == c == "inversiones ejemplo"


def test_name_key_ignores_accents():
    assert name_key("Distribuidora Módelo") == name_key("Distribuidora Modelo")


def test_name_key_removes_srl():
    assert name_key("Distribuidora Modelo S.R.L.") == "distribuidora modelo"


def test_name_key_empty_company():
    assert name_key("") == ""


def test_name_key_suffix_only_kept_when_no_token_would_remain():
    assert name_key("C.A.") == "c a"


def test_name_key_punctuation_only_falls_back_to_casefolded_original():
    assert name_key("...") == "..."


def test_normalize_tax_id():
    assert normalize_tax_id("j-12345678-9") == "J123456789"
    assert normalize_tax_id(" v 12.345.678 ") == "V12345678"


def test_is_valid_rif():
    assert is_valid_rif("J123456789")
    assert is_valid_rif("V12345678")
    assert not is_valid_rif("X123456789")
    assert not is_valid_rif("J1234567")


def test_stored_tax_id():
    assert stored_tax_id("j-12345678-9") == "J123456789"
    assert stored_tax_id("  not a rif  ") == "not a rif"


def test_assign_company_keys_shared_name():
    items = [
        ("INVERSIONES EJEMPLO, C.A.", "", "a@example.com"),
        ("Inversiones Ejemplo C A", "", "b@example.com"),
        ("inversiones  ejemplo", "", "c@example.com"),
    ]
    keys = assign_company_keys(items)
    assert keys[0] == keys[1] == keys[2] == "n:inversiones ejemplo"


def test_assign_company_keys_shared_rif():
    items = [
        ("Distribuidora Modelo", "J-12345678-9", "a@example.com"),
        ("Comercializadora Otro", "J123456789", "b@example.com"),
    ]
    keys = assign_company_keys(items)
    assert keys[0] == keys[1] == "n:distribuidora modelo"


def test_assign_company_keys_chain():
    items = [
        ("Distribuidora Modelo", "J-12345678-9", "a@example.com"),
        ("Distribuidora Modelo", "", "b@example.com"),
        ("Otro Nombre", "J123456789", "c@example.com"),
    ]
    keys = assign_company_keys(items)
    assert keys[0] == keys[1] == keys[2]


def test_assign_company_keys_no_name_no_rif():
    items = [
        ("", "", "solo@example.com"),
        ("", "", "otro@example.com"),
    ]
    keys = assign_company_keys(items)
    assert keys[0] == "e:solo@example.com"
    assert keys[1] == "e:otro@example.com"


def test_assign_company_keys_no_name_with_rif():
    items = [
        ("", "J-12345678-9", "a@example.com"),
        ("", "J123456789", "b@example.com"),
    ]
    keys = assign_company_keys(items)
    assert keys[0] == keys[1] == "t:J123456789"


def test_assign_company_keys_grouping_same_in_any_order():
    items = [
        ("Otro Nombre", "J123456789", "c@example.com"),
        ("Distribuidora Modelo", "J-12345678-9", "a@example.com"),
        ("Distribuidora Modelo", "", "b@example.com"),
    ]
    keys = assign_company_keys(items)
    assert keys[0] == keys[1] == keys[2] == "n:otro nombre"

    reversed_items = list(reversed(items))
    reversed_keys = assign_company_keys(reversed_items)
    assert reversed_keys[0] == reversed_keys[1] == reversed_keys[2] == "n:distribuidora modelo"
