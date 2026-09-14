"""Read contact spreadsheets into SourceRow records (plan D3)."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import openpyxl
import xlrd

from b2b import InputError

CLIENT_HEADERS = ("RIF", "NOMBRE", "CIUDAD", "MAIL", "AREA")
YEARBOOK_HEADERS = ("EMPRESA", "CONTACTO", "CORREO", "CIUDAD")

CLIENT_YEAR = 2020
YEARBOOK_YEAR = 2009


@dataclass(frozen=True)
class SourceRow:
    source_file: str
    source_sheet: str
    source_row: int
    source_year: int
    company: str
    contact_name: str
    city_raw: str
    tax_id_raw: str
    area: str
    email_raw: str
    company_contains_at: bool


@dataclass(frozen=True)
class SourceRead:
    source_file: str
    source_year: int
    rows: list[SourceRow]
    skipped_sheets: list[str]


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def _descriptive(value: object) -> str:
    return " ".join(cell_text(value).split())


def _cell(raw_row: list[object], index: int) -> object:
    if index < len(raw_row):
        return raw_row[index]
    return None


def _is_blank(raw_row: list[object]) -> bool:
    return all(not cell_text(value).strip() for value in raw_row)


def _mapping(kind: str, raw_row: list[object], header_index: dict[str, int]) -> dict[str, object]:
    if kind == "clients":
        company = _descriptive(_cell(raw_row, header_index["NOMBRE"]))
        return {
            "company": company,
            "contact_name": "",
            "city_raw": _descriptive(_cell(raw_row, header_index["CIUDAD"])),
            "tax_id_raw": _descriptive(_cell(raw_row, header_index["RIF"])),
            "area": _descriptive(_cell(raw_row, header_index["AREA"])),
            "email_raw": cell_text(_cell(raw_row, header_index["MAIL"])),
            "company_contains_at": "@" in company,
        }
    company = _descriptive(_cell(raw_row, header_index["EMPRESA"]))
    return {
        "company": company,
        "contact_name": _descriptive(_cell(raw_row, header_index["CONTACTO"])),
        "city_raw": _descriptive(_cell(raw_row, header_index["CIUDAD"])),
        "tax_id_raw": "",
        "area": "",
        "email_raw": cell_text(_cell(raw_row, header_index["CORREO"])),
        "company_contains_at": "@" in company,
    }


def rows_from_sheet(
    kind: Literal["clients", "yearbook"],
    source_file: str,
    sheet_name: str,
    raw_rows: list[list[object]],
) -> list[SourceRow] | None:
    non_blank = [index for index, raw_row in enumerate(raw_rows) if not _is_blank(raw_row)]
    if not non_blank or non_blank == [0]:
        return None

    required = CLIENT_HEADERS if kind == "clients" else YEARBOOK_HEADERS
    header_row = raw_rows[0]
    header_index: dict[str, int] = {}
    for index, value in enumerate(header_row):
        header_index.setdefault(cell_text(value).strip().upper(), index)
    missing = [header for header in required if header not in header_index]
    if missing:
        raise InputError(
            f"{source_file} sheet '{sheet_name}': missing header(s) {', '.join(missing)}"
        )

    source_year = CLIENT_YEAR if kind == "clients" else YEARBOOK_YEAR
    rows: list[SourceRow] = []
    for index in non_blank:
        if index == 0:
            continue
        raw_row = raw_rows[index]
        fields = _mapping(kind, raw_row, header_index)
        rows.append(
            SourceRow(
                source_file=source_file,
                source_sheet=sheet_name,
                source_row=index + 1,
                source_year=source_year,
                company=fields["company"],
                contact_name=fields["contact_name"],
                city_raw=fields["city_raw"],
                tax_id_raw=fields["tax_id_raw"],
                area=fields["area"],
                email_raw=fields["email_raw"],
                company_contains_at=fields["company_contains_at"],
            )
        )
    return rows


def read_clients(path: Path) -> SourceRead:
    if not path.exists():
        raise InputError(f"{path}: file not found")
    workbook = xlrd.open_workbook(str(path))
    rows: list[SourceRow] = []
    skipped: list[str] = []
    for sheet in workbook.sheets():
        raw_rows = [sheet.row_values(i) for i in range(sheet.nrows)]
        sheet_rows = rows_from_sheet("clients", path.name, sheet.name, raw_rows)
        if sheet_rows is None:
            skipped.append(sheet.name)
        else:
            rows.extend(sheet_rows)
    return SourceRead(
        source_file=path.name,
        source_year=CLIENT_YEAR,
        rows=rows,
        skipped_sheets=skipped,
    )


def read_yearbook(path: Path) -> SourceRead:
    if not path.exists():
        raise InputError(f"{path}: file not found")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows: list[SourceRow] = []
        skipped: list[str] = []
        for ws in workbook.worksheets:
            raw_rows = [list(r) for r in ws.iter_rows(values_only=True)]
            sheet_rows = rows_from_sheet("yearbook", path.name, ws.title, raw_rows)
            if sheet_rows is None:
                skipped.append(ws.title)
            else:
                rows.extend(sheet_rows)
    finally:
        workbook.close()
    return SourceRead(
        source_file=path.name,
        source_year=YEARBOOK_YEAR,
        rows=rows,
        skipped_sheets=skipped,
    )
