"""Spec 006 plan D5: the Artemisa users export reader (synthetic rows only)."""
import pytest

from b2b import InputError
from b2b.artemisa_csv import REJECT_REASONS, read_artemisa_csv

HEADER = "user_id,email,first_name,last_name,kyc_full_name,nickname,phone,status_kyc,paypal_offers,types,first_offer,last_offer\n"


def write(tmp_path, rows, header=HEADER, bom=True):
    path = tmp_path / "artemisa.csv"
    text = header + "".join(rows)
    path.write_bytes(("﻿" if bom else "").encode("utf-8") + text.encode("utf-8"))
    return path


def test_reads_six_columns_only(tmp_path):
    path = write(tmp_path, [
        "380,Ana@Example.com ,ANA,PEREZ,ANA PEREZ,anita,'+1 0000000000,Verificado,2,SELL,2024-07-20,2024-07-22\n",
        "381,luis@example.org,LUIS,,,, '+1 0000000001 ,Verificado,0,\"BUY,SELL\",,\n",
    ])
    result = read_artemisa_csv(path)
    assert [(r.user_id, r.email, r.first_name, r.nickname, r.types) for r in result.rows] == [
        (380, "ana@example.com", "ANA", "anita", "SELL"),
        (381, "luis@example.org", "LUIS", "", "BUY,SELL"),
    ]
    assert result.rejected == {reason: 0 for reason in REJECT_REASONS}
    assert not hasattr(result.rows[0], "last_name") and not hasattr(result.rows[0], "phone")


def test_rejects_and_counts(tmp_path):
    path = write(tmp_path, [
        "0,ana@example.com,ANA,,,,'+1 0000000000,,,SELL,,\n",          # invalid user id
        "x,ana@example.com,ANA,,,,'+1 0000000000,,,SELL,,\n",          # invalid user id
        "1,no-es-correo,ANA,,,,'+1 0000000000,,,SELL,,\n",             # invalid email
        "2,ana@example.com,ANA,,,,'+1 0000000000,,,SELL,,\n",          # kept
        "2,otra@example.com,ANA,,,,'+1 0000000000,,,SELL,,\n",         # duplicate user id
        "3,ANA@example.com,ANA,,,,'+1 0000000000,,,SELL,,\n",          # duplicate email
        "4,luis@example.org,LUIS,,,,,,,SELL,,\n",                      # kept
    ])
    result = read_artemisa_csv(path)
    assert [r.user_id for r in result.rows] == [2, 4]
    assert result.rejected == {"invalid_user_id": 2, "invalid_email": 1, "duplicate_user_id": 1, "duplicate_email": 1}


def test_missing_header(tmp_path):
    path = write(tmp_path, [], header="user_id,email,first_name,phone,types\n")
    with pytest.raises(InputError) as excinfo:
        read_artemisa_csv(path)
    assert str(excinfo.value) == f"{path}: missing header 'nickname'"


def test_without_bom_and_empty(tmp_path):
    assert read_artemisa_csv(write(tmp_path, [], bom=False)).rows == []
