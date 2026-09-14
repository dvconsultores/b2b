from __future__ import annotations

from b2b.emails import EmailExtraction, domain_of, extract, normalize_token, validate


def test_normalize_strips_whitespace_and_lowercases():
    assert normalize_token("  Ana.Perez@Example.COM ") == "ana.perez@example.com"


def test_normalize_removes_inner_spaces():
    assert normalize_token("a b@example.com") == "ab@example.com"


def test_normalize_strips_mailto_and_angle_brackets():
    assert normalize_token("mailto:<Ana@Example.com>") == "ana@example.com"


def test_validate_empty():
    assert validate("") == "empty"


def test_validate_no_at():
    assert validate("example.com") == "invalid_format"


def test_validate_two_at_in_one_token():
    assert validate("a@b@example.com") == "invalid_format"


def test_validate_non_ascii_local_part():
    assert validate("josé@example.com") == "non_ascii_local_part"


def test_validate_label_starting_with_hyphen():
    assert validate("a@-example.com") == "invalid_format"


def test_validate_numeric_tld():
    assert validate("a@example.123") == "invalid_format"


def test_validate_local_part_too_long():
    local = "a" * 65
    assert validate(f"{local}@example.com") == "invalid_format"


def test_validate_unicode_domain_accepted():
    assert validate("ejemplo@compañía.example") is None


def test_extract_single_token():
    result = extract("  Ana.Perez@Example.COM ")
    assert result == EmailExtraction(candidates=["ana.perez@example.com"], invalid=[])


def test_extract_empty_cell():
    result = extract("")
    assert result.candidates == []
    assert result.invalid == [("", "empty")]


def test_extract_two_candidates():
    result = extract("a@example.com; b@example.org")
    assert result.candidates == ["a@example.com", "b@example.org"]
    assert result.invalid == []


def test_extract_one_candidate_one_invalid():
    result = extract("a@example.com / bad@")
    assert result.candidates == ["a@example.com"]
    assert result.invalid == [("bad@", "invalid_format")]


def test_domain_of():
    assert domain_of("ana@example.com") == "example.com"
    assert domain_of("ejemplo@compañía.example") == "compañía.example"
