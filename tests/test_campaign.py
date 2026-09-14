from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from b2b import ConfigError
from b2b.campaign import (
    Campaign,
    Phrases,
    TestSample,
    contains_link_or_html,
    load_campaign,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = ROOT / "config" / "campaign.toml"

VALID = """\
name = "primer-contacto-2026"
step = 1
template = "config/templates/primer_contacto.txt"
launch_price_end = 2026-12-31
timezone = "America/Caracas"
hourly_cap = 20
batch_limit = 100
send_days = ["mon", "tue", "wed", "thu", "fri"]
send_start = "08:00"
send_end = "17:00"
bounce_pause_threshold = 0.02
bounce_min_sends = 20
temporary_failure_limit = 3
test_sample_count = 3

[phrases]
greeting_with_name = "Hola {nombre},"
greeting_without_name = "Hola,"
opening_with_city = "Vi que {empresa} está en {ciudad} y quería hacerle una pregunta rápida: ¿todavía calculan la nómina a mano o en hojas de cálculo?"
opening_without_city = "Quería hacerle una pregunta rápida sobre la nómina de {empresa}: ¿todavía la calculan a mano o en hojas de cálculo?"
company_fallback = "su empresa"
opt_out = "P. D.: Si no es de su interés, responda \\"no\\" y no le vuelvo a escribir."

[test_sample]
nombre = "ANA PÉREZ"
empresa = "EMPRESA EJEMPLO, C.A."
ciudad = "Caracas"
"""


def write(tmp_path: Path, text: str) -> Path:
    target = tmp_path / "campaign.toml"
    target.write_text(text, encoding="utf-8")
    return target


def load(tmp_path: Path, text: str) -> Campaign:
    return load_campaign(write(tmp_path, text))


def test_real_config_loads() -> None:
    campaign = load_campaign(REAL_CONFIG)
    assert isinstance(campaign, Campaign)
    assert campaign.name == "primer-contacto-2026-b"
    assert campaign.allowed_verification == ("valid", "unverified")
    assert campaign.source_years == (2020,)
    assert campaign.continuous is True
    assert campaign.step == 1
    assert campaign.template == Path("config/templates/primer_contacto.txt")
    assert campaign.launch_price_end == date(2026, 12, 31)
    assert campaign.timezone == "America/Caracas"
    assert campaign.hourly_cap == 20
    assert campaign.batch_limit == 100
    assert campaign.send_days == ("mon", "tue", "wed", "thu", "fri")
    assert campaign.send_start == time(8, 0)
    assert campaign.send_end == time(17, 0)
    assert campaign.bounce_pause_threshold == 0.02
    assert campaign.bounce_min_sends == 20
    assert campaign.temporary_failure_limit == 3
    assert campaign.test_sample_count == 3
    assert isinstance(campaign.phrases, Phrases)
    assert isinstance(campaign.test_sample, TestSample)


def test_valid_synthetic_loads(tmp_path: Path) -> None:
    campaign = load(tmp_path, VALID)
    assert campaign.name == "primer-contacto-2026"
    assert campaign.phrases.greeting_with_name == "Hola {nombre},"
    assert campaign.test_sample.ciudad == "Caracas"
    assert campaign.allowed_verification == ("valid",)
    assert campaign.source_years == (2020, 2009)
    assert campaign.continuous is False


def test_source_years_and_continuous(tmp_path: Path) -> None:
    text = VALID.replace("test_sample_count = 3\n", "test_sample_count = 3\nsource_years = [2020]\ncontinuous = true\n")
    campaign = load(tmp_path, text)
    assert (campaign.source_years, campaign.continuous) == ((2020,), True)


@pytest.mark.parametrize("line, message", [
    ("source_years = 2020", "'source_years' has the wrong type"),
    ('source_years = ["2020"]', "'source_years' has the wrong type"),
    ("source_years = []", "'source_years' is invalid"),
    ("source_years = [2020, 2020]", "'source_years' is invalid"),
    ("source_years = [2015]", "'source_years' is invalid"),
    ('continuous = "yes"', "'continuous' has the wrong type"),
    ("continuous = 1", "'continuous' has the wrong type"),
])
def test_bad_source_years_or_continuous(tmp_path: Path, line: str, message: str) -> None:
    path = write(tmp_path, VALID.replace("test_sample_count = 3\n", f"test_sample_count = 3\n{line}\n"))
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: {message}"


def test_allowed_verification_list(tmp_path: Path) -> None:
    text = VALID.replace("test_sample_count = 3\n", 'test_sample_count = 3\nallowed_verification = ["valid", "catch_all"]\n')
    assert load(tmp_path, text).allowed_verification == ("valid", "catch_all")


@pytest.mark.parametrize("literal, problem", [
    ('"valid"', "has the wrong type"),
    ("[1]", "has the wrong type"),
    ("[]", "is invalid"),
    ('["valid", "valid"]', "is invalid"),
    ('["invalid"]', "is invalid"),
    ('["bogus"]', "is invalid"),
])
def test_bad_allowed_verification(tmp_path: Path, literal: str, problem: str) -> None:
    path = write(tmp_path, VALID.replace("test_sample_count = 3\n", f"test_sample_count = 3\nallowed_verification = {literal}\n"))
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'allowed_verification' {problem}"


def test_invalid_toml(tmp_path: Path) -> None:
    path = write(tmp_path, "name = \n")
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: invalid TOML"


def test_unknown_top_level_key(tmp_path: Path) -> None:
    path = write(tmp_path, VALID.replace('step = 1\n', 'step = 1\nextra = 1\n'))
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: unknown key 'extra'"


def test_unknown_phrase_key(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        VALID.replace(
            'company_fallback = "su empresa"\n',
            'company_fallback = "su empresa"\nextra = "x"\n',
        ),
    )
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: unknown key 'phrases.extra'"


def test_unknown_test_sample_key(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        VALID.replace('ciudad = "Caracas"\n', 'ciudad = "Caracas"\nextra = "x"\n'),
    )
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: unknown key 'test_sample.extra'"


def test_missing_required_key(tmp_path: Path) -> None:
    text = VALID.replace('name = "primer-contacto-2026"\n', "")
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: missing key 'name'"


def test_missing_phrase_key(tmp_path: Path) -> None:
    text = VALID.replace('company_fallback = "su empresa"\n', "")
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: missing key 'phrases.company_fallback'"


def test_wrong_type_int(tmp_path: Path) -> None:
    text = VALID.replace("hourly_cap = 20", 'hourly_cap = "20"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'hourly_cap' has the wrong type"


def test_wrong_type_bool_not_int(tmp_path: Path) -> None:
    text = VALID.replace("hourly_cap = 20", "hourly_cap = true")
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'hourly_cap' has the wrong type"


def test_wrong_type_bool_not_float(tmp_path: Path) -> None:
    text = VALID.replace("bounce_pause_threshold = 0.02", "bounce_pause_threshold = true")
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'bounce_pause_threshold' has the wrong type"


def test_name_regex_invalid(tmp_path: Path) -> None:
    text = VALID.replace('name = "primer-contacto-2026"', 'name = "AB"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'name' is invalid"


def test_step_not_one(tmp_path: Path) -> None:
    text = VALID.replace("step = 1", "step = 2")
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'step' is invalid"


def test_template_empty(tmp_path: Path) -> None:
    text = VALID.replace(
        'template = "config/templates/primer_contacto.txt"', 'template = ""'
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'template' is invalid"


def test_launch_price_end_not_date(tmp_path: Path) -> None:
    text = VALID.replace("launch_price_end = 2026-12-31", 'launch_price_end = "2026-12-31"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'launch_price_end' has the wrong type"


def test_launch_price_end_datetime(tmp_path: Path) -> None:
    text = VALID.replace(
        "launch_price_end = 2026-12-31", "launch_price_end = 2026-12-31T10:00:00"
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'launch_price_end' has the wrong type"


def test_invalid_timezone(tmp_path: Path) -> None:
    text = VALID.replace('timezone = "America/Caracas"', 'timezone = "Not/AZone"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'timezone' is invalid"


def test_out_of_range_integer(tmp_path: Path) -> None:
    text = VALID.replace("hourly_cap = 20", "hourly_cap = 0")
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'hourly_cap' is invalid"


def test_bad_bounce_pause_threshold(tmp_path: Path) -> None:
    text = VALID.replace("bounce_pause_threshold = 0.02", "bounce_pause_threshold = 0.5")
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'bounce_pause_threshold' is invalid"


def test_send_days_empty(tmp_path: Path) -> None:
    text = VALID.replace(
        'send_days = ["mon", "tue", "wed", "thu", "fri"]', "send_days = []"
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'send_days' is invalid"


def test_send_days_invalid_value(tmp_path: Path) -> None:
    text = VALID.replace(
        'send_days = ["mon", "tue", "wed", "thu", "fri"]', 'send_days = ["monday"]'
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'send_days' is invalid"


def test_send_days_duplicate(tmp_path: Path) -> None:
    text = VALID.replace(
        'send_days = ["mon", "tue", "wed", "thu", "fri"]', 'send_days = ["mon", "mon"]'
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'send_days' is invalid"


def test_send_start_bad_format(tmp_path: Path) -> None:
    text = VALID.replace('send_start = "08:00"', 'send_start = "8:00"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'send_start' is invalid"


def test_send_end_bad_format(tmp_path: Path) -> None:
    text = VALID.replace('send_end = "17:00"', 'send_end = "25:00"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'send_end' is invalid"


def test_send_end_not_after_start(tmp_path: Path) -> None:
    text = VALID.replace('send_end = "17:00"', 'send_end = "08:00"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'send_end' is invalid"


def test_phrase_placeholder_mismatch(tmp_path: Path) -> None:
    text = VALID.replace('greeting_with_name = "Hola {nombre},"', 'greeting_with_name = "Hola,"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'phrases.greeting_with_name' is invalid"


def test_phrase_extra_placeholder(tmp_path: Path) -> None:
    text = VALID.replace(
        'greeting_without_name = "Hola,"', 'greeting_without_name = "Hola {nombre},"'
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'phrases.greeting_without_name' is invalid"


def test_phrase_conversion_invalid(tmp_path: Path) -> None:
    text = VALID.replace(
        'greeting_with_name = "Hola {nombre},"', 'greeting_with_name = "Hola {nombre!r},"'
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'phrases.greeting_with_name' is invalid"


def test_phrase_format_spec_invalid(tmp_path: Path) -> None:
    text = VALID.replace(
        'greeting_with_name = "Hola {nombre},"', 'greeting_with_name = "Hola {nombre:>3},"'
    )
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'phrases.greeting_with_name' is invalid"


def test_phrase_stray_brace_invalid(tmp_path: Path) -> None:
    text = VALID.replace('greeting_without_name = "Hola,"', 'greeting_without_name = "Hola {"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'phrases.greeting_without_name' is invalid"


def test_phrase_contains_link(tmp_path: Path) -> None:
    text = VALID.replace('company_fallback = "su empresa"', 'company_fallback = "ejemplo.com"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'phrases.company_fallback' contains a link or HTML"


def test_test_sample_contains_html(tmp_path: Path) -> None:
    text = VALID.replace('ciudad = "Caracas"', 'ciudad = "<b>Caracas</b>"')
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_campaign(path)
    assert str(excinfo.value) == f"{path}: 'test_sample.ciudad' contains a link or HTML"


def test_defaults_applied(tmp_path: Path) -> None:
    text = """\
name = "primer-contacto-2026"
template = "config/templates/primer_contacto.txt"
launch_price_end = 2026-12-31

[phrases]
greeting_with_name = "Hola {nombre},"
greeting_without_name = "Hola,"
opening_with_city = "Vi que {empresa} está en {ciudad}."
opening_without_city = "Quería hablar de {empresa}."
company_fallback = "su empresa"
opt_out = "P. D.: responda no."

[test_sample]
nombre = "ANA PÉREZ"
empresa = "EMPRESA EJEMPLO, C.A."
ciudad = "Caracas"
"""
    campaign = load(tmp_path, text)
    assert campaign.step == 1
    assert campaign.timezone == "America/Caracas"
    assert campaign.hourly_cap == 20
    assert campaign.batch_limit == 100
    assert campaign.send_days == ("mon", "tue", "wed", "thu", "fri")
    assert campaign.send_start == time(8, 0)
    assert campaign.send_end == time(17, 0)
    assert campaign.bounce_pause_threshold == 0.02
    assert campaign.bounce_min_sends == 20
    assert campaign.temporary_failure_limit == 3
    assert campaign.test_sample_count == 3


@pytest.mark.parametrize(
    "text",
    ["https://x", "www.ejemplo", "ejemplo.com", "<b>", "&nbsp;"],
)
def test_contains_link_or_html_true(text: str) -> None:
    assert contains_link_or_html(text) is True


@pytest.mark.parametrize(
    "text",
    ["C.A.", "S.R.L.", "Nómina Atenea", "P. D.:"],
)
def test_contains_link_or_html_false(text: str) -> None:
    assert contains_link_or_html(text) is False
