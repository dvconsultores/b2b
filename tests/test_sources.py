"""Tests for b2b.sources (spec 001, task T007)."""
from __future__ import annotations

import datetime

import pytest

from b2b import InputError
from b2b.sources import (
    CLIENT_HEADERS,
    YEARBOOK_HEADERS,
    SourceRead,
    SourceRow,
    cell_text,
    read_clients,
    read_yearbook,
    rows_from_sheet,
)

CLIENT_HEADER_ROW = ["RIF", "NOMBRE", "DIR1", "DIR2", "DIR3", "TLF", "CIUDAD", "MAIL", "AREA"]
YEARBOOK_HEADER_ROW = ["EMPRESA", "CONTACTO", "CORREO", "CIUDAD"]


def test_cell_text_none_is_empty():
    assert cell_text(None) == ""


def test_cell_text_integral_float():
    assert cell_text(12345.0) == "12345"


def test_cell_text_non_integral_float():
    assert cell_text(1.5) == "1.5"


def test_cell_text_datetime_and_date():
    assert cell_text(datetime.datetime(2020, 2, 3, 4, 5, 6)) == "2020-02-03T04:05:06"
    assert cell_text(datetime.date(2020, 2, 3)) == "2020-02-03"


def test_cell_text_bool():
    assert cell_text(True) == "TRUE"
    assert cell_text(False) == "FALSE"


def test_cell_text_other():
    assert cell_text("Acme S.A.") == "Acme S.A."


def test_rows_from_sheet_empty_sheet_skipped():
    assert rows_from_sheet("clients", "ClientesFebrero2020.xls", "SQL", []) is None


def test_rows_from_sheet_header_only_skipped():
    assert rows_from_sheet("clients", "ClientesFebrero2020.xls", "Clientes", [CLIENT_HEADER_ROW]) is None


def test_rows_from_sheet_blank_rows_only_skipped():
    raw_rows = [CLIENT_HEADER_ROW, ["", None, "  ", "", "", "", "", "", ""]]
    assert rows_from_sheet("clients", "ClientesFebrero2020.xls", "Clientes", raw_rows) is None


def test_rows_from_sheet_missing_header_raises():
    raw_rows = [["RIF", "NOMBRE", "CIUDAD", "MAIL"], ["J-1", "Acme S.A.", "Caracas", "ana@example.com"]]
    with pytest.raises(InputError) as excinfo:
        rows_from_sheet("clients", "ClientesFebrero2020.xls", "Clientes", raw_rows)
    message = str(excinfo.value)
    assert "ClientesFebrero2020.xls" in message
    assert "Clientes" in message
    assert "AREA" in message


def test_rows_from_sheet_missing_header_yearbook_raises():
    raw_rows = [["EMPRESA", "CONTACTO", "CIUDAD"], ["Acme S.A.", "Ana", "Caracas"]]
    with pytest.raises(InputError) as excinfo:
        rows_from_sheet("yearbook", "Year Book 2009.xlsx", "1-100", raw_rows)
    message = str(excinfo.value)
    assert "Year Book 2009.xlsx" in message
    assert "1-100" in message
    assert "CORREO" in message


def test_rows_from_sheet_blank_rows_ignored_and_row_numbers_kept():
    raw_rows = [
        CLIENT_HEADER_ROW,
        ["J-1", "Acme S.A.", "", "", "", "", "Caracas", "ana@example.com", "Area 1"],
        ["", None, "", "", "", "", "", "", ""],
        ["J-2", "Beta C.A.", "", "", "", "", "Valencia", "beto@example.com", "Area 2"],
    ]
    rows = rows_from_sheet("clients", "ClientesFebrero2020.xls", "Clientes", raw_rows)
    assert rows is not None
    assert [row.source_row for row in rows] == [2, 4]


def test_rows_from_sheet_short_row_counts_as_empty_cells():
    raw_rows = [
        CLIENT_HEADER_ROW,
        ["J-1", "Acme S.A."],
    ]
    rows = rows_from_sheet("clients", "ClientesFebrero2020.xls", "Clientes", raw_rows)
    assert rows is not None
    assert len(rows) == 1
    assert rows[0].company == "Acme S.A."
    assert rows[0].city_raw == ""
    assert rows[0].email_raw == ""


def test_rows_from_sheet_whitespace_collapsed_but_not_email():
    raw_rows = [
        CLIENT_HEADER_ROW,
        ["J-1", "  Acme   S.A.  ", "", "", "", "", "  Cara   cas ", "  ana@example.com  ", " Area  1 "],
    ]
    rows = rows_from_sheet("clients", "ClientesFebrero2020.xls", "Clientes", raw_rows)
    assert rows is not None
    row = rows[0]
    assert row.company == "Acme S.A."
    assert row.city_raw == "Cara cas"
    assert row.area == "Area 1"
    assert row.email_raw == "  ana@example.com  "


def test_rows_from_sheet_clients_mapping():
    raw_rows = [
        CLIENT_HEADER_ROW,
        ["J-1", "Acme S.A.", "", "", "", "", "Caracas", "ana@example.com", "Area 1"],
    ]
    rows = rows_from_sheet("clients", "ClientesFebrero2020.xls", "Clientes", raw_rows)
    assert rows is not None
    row = rows[0]
    assert row.source_file == "ClientesFebrero2020.xls"
    assert row.source_sheet == "Clientes"
    assert row.source_row == 2
    assert row.source_year == 2020
    assert row.company == "Acme S.A."
    assert row.contact_name == ""
    assert row.city_raw == "Caracas"
    assert row.tax_id_raw == "J-1"
    assert row.area == "Area 1"
    assert row.email_raw == "ana@example.com"
    assert row.company_contains_at is False


def test_rows_from_sheet_yearbook_mapping():
    raw_rows = [
        YEARBOOK_HEADER_ROW,
        ["Acme S.A.", "Ana", "ana@example.com", "Caracas"],
    ]
    rows = rows_from_sheet("yearbook", "Year Book 2009.xlsx", "1-100", raw_rows)
    assert rows is not None
    row = rows[0]
    assert row.source_file == "Year Book 2009.xlsx"
    assert row.source_sheet == "1-100"
    assert row.source_row == 2
    assert row.source_year == 2009
    assert row.company == "Acme S.A."
    assert row.contact_name == "Ana"
    assert row.city_raw == "Caracas"
    assert row.tax_id_raw == ""
    assert row.area == ""
    assert row.email_raw == "ana@example.com"
    assert row.company_contains_at is False


def test_rows_from_sheet_company_contains_at():
    raw_rows = [
        YEARBOOK_HEADER_ROW,
        ["ana@example.com", "Ana", "ana@example.com", "Caracas"],
    ]
    rows = rows_from_sheet("yearbook", "Year Book 2009.xlsx", "1-100", raw_rows)
    assert rows is not None
    assert rows[0].company_contains_at is True


def test_read_clients_missing_file(tmp_path):
    path = tmp_path / "ClientesFebrero2020.xls"
    with pytest.raises(InputError) as excinfo:
        read_clients(path)
    assert str(path) in str(excinfo.value)
    assert "file not found" in str(excinfo.value)


def test_read_clients_skips_empty_and_header_only_sheets(stub_xls):
    path = stub_xls(
        {
            "Clientes": [
                CLIENT_HEADER_ROW,
                ["J-1", "Acme S.A.", "", "", "", "", "Caracas", "ana@example.com", "Area 1"],
            ],
            "SQL": [],
            "Extra": [CLIENT_HEADER_ROW],
        }
    )
    result = read_clients(path)
    assert isinstance(result, SourceRead)
    assert result.source_file == "ClientesFebrero2020.xls"
    assert result.source_year == 2020
    assert len(result.rows) == 1
    assert result.skipped_sheets == ["SQL", "Extra"]


def test_read_clients_aggregates_sheets_in_order(stub_xls):
    path = stub_xls(
        {
            "Clientes": [
                CLIENT_HEADER_ROW,
                ["J-1", "Acme S.A.", "", "", "", "", "Caracas", "ana@example.com", "Area 1"],
            ],
            "Otros": [
                CLIENT_HEADER_ROW,
                ["J-2", "Beta C.A.", "", "", "", "", "Valencia", "beto@example.com", "Area 2"],
            ],
        }
    )
    result = read_clients(path)
    assert [row.source_sheet for row in result.rows] == ["Clientes", "Otros"]
    assert result.skipped_sheets == []


def test_read_clients_missing_header_raises(stub_xls):
    path = stub_xls({"Clientes": [["RIF", "NOMBRE", "CIUDAD", "MAIL"], ["J-1", "Acme S.A.", "Caracas", "ana@example.com"]]})
    with pytest.raises(InputError) as excinfo:
        read_clients(path)
    message = str(excinfo.value)
    assert "ClientesFebrero2020.xls" in message
    assert "Clientes" in message
    assert "AREA" in message


def test_read_clients_integral_float(stub_xls):
    path = stub_xls(
        {
            "Clientes": [
                CLIENT_HEADER_ROW,
                [12345.0, "Acme S.A.", "", "", "", "", "Caracas", "ana@example.com", "Area 1"],
            ]
        }
    )
    result = read_clients(path)
    assert result.rows[0].tax_id_raw == "12345"


def test_read_yearbook_missing_file(tmp_path):
    path = tmp_path / "Year Book 2009.xlsx"
    with pytest.raises(InputError) as excinfo:
        read_yearbook(path)
    assert str(path) in str(excinfo.value)
    assert "file not found" in str(excinfo.value)


def test_read_yearbook_skips_header_only_sheet(yearbook_xlsx):
    path = yearbook_xlsx(
        {
            "1-100": [
                YEARBOOK_HEADER_ROW,
                ["Acme S.A.", "Ana", "ana@example.com", "Caracas"],
            ],
            "14-100": [YEARBOOK_HEADER_ROW],
        }
    )
    result = read_yearbook(path)
    assert isinstance(result, SourceRead)
    assert result.source_file == "Year Book 2009.xlsx"
    assert result.source_year == 2009
    assert len(result.rows) == 1
    assert result.skipped_sheets == ["14-100"]


def test_read_yearbook_aggregates_sheets_in_order(yearbook_xlsx):
    path = yearbook_xlsx(
        {
            "1-100": [
                YEARBOOK_HEADER_ROW,
                ["Acme S.A.", "Ana", "ana@example.com", "Caracas"],
            ],
            "2-100": [
                YEARBOOK_HEADER_ROW,
                ["Beta C.A.", "Beto", "beto@example.com", "Valencia"],
            ],
        }
    )
    result = read_yearbook(path)
    assert [row.source_sheet for row in result.rows] == ["1-100", "2-100"]
    assert result.skipped_sheets == []


def test_read_yearbook_missing_header_raises(yearbook_xlsx):
    path = yearbook_xlsx({"1-100": [["EMPRESA", "CONTACTO", "CIUDAD"], ["Acme S.A.", "Ana", "Caracas"]]})
    with pytest.raises(InputError) as excinfo:
        read_yearbook(path)
    message = str(excinfo.value)
    assert "Year Book 2009.xlsx" in message
    assert "1-100" in message
    assert "CORREO" in message


def test_read_yearbook_blank_rows_ignored_and_row_numbers_kept(yearbook_xlsx):
    path = yearbook_xlsx(
        {
            "1-100": [
                YEARBOOK_HEADER_ROW,
                ["Acme S.A.", "Ana", "ana@example.com", "Caracas"],
                [None, None, None, None],
                ["Beta C.A.", "Beto", "beto@example.com", "Valencia"],
            ]
        }
    )
    result = read_yearbook(path)
    assert [row.source_row for row in result.rows] == [2, 4]


def test_read_yearbook_whitespace_collapsed_but_not_email(yearbook_xlsx):
    path = yearbook_xlsx(
        {
            "1-100": [
                YEARBOOK_HEADER_ROW,
                ["  Acme   S.A.  ", "  Ana   Maria ", "  ana@example.com  ", "  Cara   cas "],
            ]
        }
    )
    result = read_yearbook(path)
    row = result.rows[0]
    assert row.company == "Acme S.A."
    assert row.contact_name == "Ana Maria"
    assert row.city_raw == "Cara cas"
    assert row.email_raw == "  ana@example.com  "


def test_read_yearbook_integral_float(yearbook_xlsx):
    path = yearbook_xlsx(
        {
            "1-100": [
                YEARBOOK_HEADER_ROW,
                ["Acme S.A.", "Ana", "ana@example.com", 12345.0],
            ]
        }
    )
    result = read_yearbook(path)
    assert result.rows[0].city_raw == "12345"


def test_source_row_is_frozen():
    row = SourceRow(
        source_file="ClientesFebrero2020.xls",
        source_sheet="Clientes",
        source_row=2,
        source_year=2020,
        company="Acme S.A.",
        contact_name="",
        city_raw="Caracas",
        tax_id_raw="J-1",
        area="Area 1",
        email_raw="ana@example.com",
        company_contains_at=False,
    )
    with pytest.raises(Exception):
        row.company = "Other"  # type: ignore[misc]


def test_headers_constants():
    assert CLIENT_HEADERS == ("RIF", "NOMBRE", "CIUDAD", "MAIL", "AREA")
    assert YEARBOOK_HEADERS == ("EMPRESA", "CONTACTO", "CORREO", "CIUDAD")
