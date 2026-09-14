"""Tests for b2b.classify."""

from __future__ import annotations

from pathlib import Path

import pytest

from b2b import ConfigError
from b2b.classify import classify, load_role_words, reduce_local_part


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "role_words.txt"
    path.write_text(content, encoding="utf-8")
    return path


def test_generic_addresses(tmp_path: Path) -> None:
    words = load_role_words(
        _write(
            tmp_path,
            "info\nventas\natencionalcliente\nrrhh\n",
        )
    )
    assert classify("info@example.com", words) == "generic"
    assert classify("ventas2@example.com", words) == "generic"
    assert classify("atencion.al-cliente@example.com", words) == "generic"
    assert classify("rrhh_01@example.com", words) == "generic"


def test_personal_addresses(tmp_path: Path) -> None:
    words = load_role_words(
        _write(
            tmp_path,
            "info\nventas\natencionalcliente\nrrhh\n",
        )
    )
    assert classify("ana.perez@example.com", words) == "personal"
    assert classify("jperez@example.com", words) == "personal"
    assert classify("info.ana@example.com", words) == "personal"


def test_reduce_local_part() -> None:
    assert reduce_local_part("ventas2") == "ventas"
    assert reduce_local_part("atencion.al-cliente") == "atencionalcliente"
    assert reduce_local_part("rrhh_01") == "rrhh"


def test_comments_and_blank_lines_ignored(tmp_path: Path) -> None:
    words = load_role_words(
        _write(
            tmp_path,
            "# a comment\n\n  info  \n\n# another\nventas\n",
        )
    )
    assert words == frozenset({"info", "ventas"})


def test_bad_line_raises_config_error_with_line_number(tmp_path: Path) -> None:
    path = _write(tmp_path, "# comment\ninfo\nbad word\n")
    with pytest.raises(ConfigError) as excinfo:
        load_role_words(path)
    assert "line 3" in str(excinfo.value)


def test_bad_line_with_digits_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "info\nventas2\n")
    with pytest.raises(ConfigError) as excinfo:
        load_role_words(path)
    assert "line 2" in str(excinfo.value)


def test_load_real_role_words() -> None:
    path = Path(__file__).resolve().parents[1] / "config" / "role_words.txt"
    words = load_role_words(path)
    assert "info" in words
