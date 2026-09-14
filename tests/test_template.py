from __future__ import annotations

from pathlib import Path

import pytest

from b2b import ConfigError
from b2b.campaign import Phrases
from b2b.template import (
    RenderedEmail,
    display_company,
    first_name,
    load_template,
    render,
    rendered_has_link,
)

OPT_OUT = 'P. D.: Si no es de su interés, responda "no" y no le vuelvo a escribir.'

PHRASES = Phrases(
    greeting_with_name="Hola {nombre},",
    greeting_without_name="Hola,",
    opening_with_city=(
        "Vi que {empresa} está en {ciudad} y quería hacerle una pregunta rápida: "
        "¿todavía calculan la nómina a mano o en hojas de cálculo?"
    ),
    opening_without_city=(
        "Quería hacerle una pregunta rápida sobre la nómina de {empresa}: "
        "¿todavía la calculan a mano o en hojas de cálculo?"
    ),
    company_fallback="su empresa",
    opt_out=OPT_OUT,
)

REAL_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "config" / "templates" / "primer_contacto.txt"
)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "template.txt"
    path.write_text(content, encoding="utf-8")
    return path


def test_real_template_loads() -> None:
    template = load_template(REAL_TEMPLATE, OPT_OUT)
    assert template.subject
    assert template.body


def test_line_1_format(tmp_path: Path) -> None:
    path = _write(tmp_path, "Hola\n\nbody\n")
    with pytest.raises(ConfigError) as exc:
        load_template(path, OPT_OUT)
    assert str(exc.value) == f"{path}: line 1 must be 'Asunto: <subject>'"


def test_line_2_not_empty(tmp_path: Path) -> None:
    path = _write(tmp_path, "Asunto: Hola\nnot empty\nbody\n")
    with pytest.raises(ConfigError) as exc:
        load_template(path, OPT_OUT)
    assert str(exc.value) == f"{path}: line 2 must be empty"


def test_empty_body(tmp_path: Path) -> None:
    path = _write(tmp_path, "Asunto: Hola\n\n\n\n")
    with pytest.raises(ConfigError) as exc:
        load_template(path, OPT_OUT)
    assert str(exc.value) == f"{path}: body is empty"


def test_invalid_braces(tmp_path: Path) -> None:
    path = _write(tmp_path, "Asunto: Hola {empresa\n\nbody\n")
    with pytest.raises(ConfigError) as exc:
        load_template(path, OPT_OUT)
    assert str(exc.value) == f"{path}: invalid braces"


def test_unknown_placeholder(tmp_path: Path) -> None:
    path = _write(tmp_path, "Asunto: Hola {empresa}\n\nbody {otro}\n")
    with pytest.raises(ConfigError) as exc:
        load_template(path, OPT_OUT)
    assert str(exc.value) == f"{path}: unknown placeholder 'otro'"


def test_link_not_allowed(tmp_path: Path) -> None:
    path = _write(tmp_path, "Asunto: Hola {empresa}\n\nvisite www.example.com\n")
    with pytest.raises(ConfigError) as exc:
        load_template(path, OPT_OUT)
    assert str(exc.value) == f"{path}: link or domain not allowed in template"


def test_html_not_allowed(tmp_path: Path) -> None:
    path = _write(tmp_path, "Asunto: Hola {empresa}\n\n<b>body</b>\n")
    with pytest.raises(ConfigError) as exc:
        load_template(path, OPT_OUT)
    assert str(exc.value) == f"{path}: HTML not allowed in template"


def test_opt_out_not_allowed(tmp_path: Path) -> None:
    path = _write(tmp_path, f"Asunto: Hola {{empresa}}\n\nbody\n{OPT_OUT}\n")
    with pytest.raises(ConfigError) as exc:
        load_template(path, OPT_OUT)
    assert str(exc.value) == f"{path}: remove the opt-out sentence; it is added automatically"


def test_display_company_examples() -> None:
    assert display_company("INVERSIONES EJEMPLO, C.A.", "su empresa") == "Inversiones Ejemplo, C.A."
    assert (
        display_company("DISTRIBUIDORA DE LA COSTA S.R.L.", "su empresa")
        == "Distribuidora de la Costa S.R.L."
    )
    assert display_company("CORPORACIÓN PDV C.A", "su empresa") == "Corporación PDV C.A."
    assert display_company("Tienda Mixta, C.A.", "su empresa") == "Tienda Mixta, C.A."
    assert display_company("", "su empresa") == "su empresa"


def test_display_company_parentheses() -> None:
    assert (
        display_company("DISTRIBUIDORA (CARACAS) C.A.", "su empresa")
        == "Distribuidora (Caracas) C.A."
    )


def test_first_name_examples() -> None:
    assert first_name("ING. PEDRO PÉREZ") == "Pedro"
    assert first_name("Dra. Luisa Gómez") == "Luisa"
    assert first_name("") == ""
    assert first_name("ventas2") == ""


def test_render_with_name_and_city() -> None:
    template = load_template(REAL_TEMPLATE, OPT_OUT)
    email = render(
        template,
        PHRASES,
        to="ana@example.com",
        contact_id=1,
        company="Inversiones Ejemplo, C.A.",
        contact_name="ING. PEDRO PÉREZ",
        city="Caracas",
        sender_name="Ana",
    )
    assert email.to == "ana@example.com"
    assert email.contact_id == 1
    assert "Inversiones Ejemplo, C.A." in email.subject
    assert "Hola Pedro," in email.body
    assert "Caracas" in email.body
    assert email.body.endswith(PHRASES.opt_out + "\n")


def test_render_without_name() -> None:
    template = load_template(REAL_TEMPLATE, OPT_OUT)
    email = render(
        template,
        PHRASES,
        to="ana@example.com",
        contact_id=None,
        company="Inversiones Ejemplo, C.A.",
        contact_name="",
        city="Caracas",
        sender_name="Ana",
    )
    assert "Hola," in email.body
    assert "Hola ," not in email.body


def test_render_without_city() -> None:
    template = load_template(REAL_TEMPLATE, OPT_OUT)
    email = render(
        template,
        PHRASES,
        to="ana@example.com",
        contact_id=None,
        company="Inversiones Ejemplo, C.A.",
        contact_name="Pedro",
        city="",
        sender_name="Ana",
    )
    assert "Caracas" not in email.body
    assert "Inversiones Ejemplo, C.A." in email.body


def test_render_without_company() -> None:
    template = load_template(REAL_TEMPLATE, OPT_OUT)
    email = render(
        template,
        PHRASES,
        to="ana@example.com",
        contact_id=None,
        company="",
        contact_name="Pedro",
        city="Caracas",
        sender_name="Ana",
    )
    assert "su empresa" in email.subject
    assert "su empresa" in email.body


def test_rendered_has_link() -> None:
    template = load_template(REAL_TEMPLATE, OPT_OUT)
    email = render(
        template,
        PHRASES,
        to="ana@example.com",
        contact_id=None,
        company="Tienda.com",
        contact_name="Pedro",
        city="Caracas",
        sender_name="Ana",
    )
    assert rendered_has_link(email) is True


def test_rendered_has_no_link() -> None:
    template = load_template(REAL_TEMPLATE, OPT_OUT)
    email = render(
        template,
        PHRASES,
        to="ana@example.com",
        contact_id=None,
        company="Inversiones Ejemplo, C.A.",
        contact_name="Pedro",
        city="Caracas",
        sender_name="Ana",
    )
    assert rendered_has_link(email) is False
