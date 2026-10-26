"""Artemisa campaign config (`config/artemisa.toml`), template and rendering (spec 006 plan D2, D3).
Same validation style as `b2b/campaign.py` and `b2b/template.py`; links are allowed, HTML is not."""
from __future__ import annotations

import re
import string
import tomllib
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from b2b import ConfigError
from b2b.campaign import HTML_PATTERN
from b2b.template import RenderedEmail, Template
from b2b.template import first_name as _first_name

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_TOP_KEYS = (
    "name", "template", "images", "timezone", "hourly_cap", "daily_cap", "send_days", "send_start",
    "send_end", "bounce_pause_threshold", "bounce_min_sends", "temporary_failure_limit", "phrases",
    "test_sample",
)
_REQUIRED_TOP = ("name", "template", "images")
_PHRASES_KEYS = ("greeting_with_name", "greeting_without_name", "opt_out")
_TEST_SAMPLE_KEYS = ("nombre",)
_PHRASE_FIELDS = {"greeting_with_name": {"nombre"}, "greeting_without_name": set(), "opt_out": set()}

_DEFAULTS = {
    "timezone": "America/Caracas",
    "hourly_cap": 40,
    "daily_cap": 400,
    "send_days": list(_DAYS),
    "send_start": "09:00",
    "send_end": "21:00",
    "bounce_pause_threshold": 0.05,
    "bounce_min_sends": 20,
    "temporary_failure_limit": 3,
}

BODY_PLACEHOLDERS = frozenset({"saludo", "remitente"})


@dataclass(frozen=True)
class ArtemisaPhrases:
    greeting_with_name: str
    greeting_without_name: str
    opt_out: str


@dataclass(frozen=True)
class ArtemisaTestSample:
    nombre: str


@dataclass(frozen=True)
class ArtemisaCampaign:
    name: str
    template: Path
    images: tuple[Path, ...]
    timezone: str
    hourly_cap: int
    daily_cap: int
    send_days: tuple[str, ...]
    send_start: time
    send_end: time
    bounce_pause_threshold: float
    bounce_min_sends: int
    temporary_failure_limit: int
    phrases: ArtemisaPhrases
    test_sample: ArtemisaTestSample
    step: int = 1  # b2b.pacing and b2b.preview read it; the campaign has one step


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return _is_int(value) or (isinstance(value, float) and not isinstance(value, bool))


def _fields(text: str, error: ConfigError) -> set[str]:
    names: set[str] = set()
    try:
        for _literal, name, format_spec, conversion in string.Formatter().parse(text):
            if name is None:
                continue
            if format_spec or conversion is not None:
                raise error
            names.add(name)
    except ValueError:
        raise error from None
    return names


def _check_string(key: str, value: object, path: Path) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{path}: '{key}' has the wrong type")
    if HTML_PATTERN.search(value):
        raise ConfigError(f"{path}: '{key}' contains HTML")
    return value


def _int_in(data: dict, key: str, low: int, high: int, path: Path) -> int:
    value = data.get(key, _DEFAULTS[key])
    if not _is_int(value):
        raise ConfigError(f"{path}: '{key}' has the wrong type")
    if not low <= value <= high:
        raise ConfigError(f"{path}: '{key}' is invalid")
    return value


def _time_value(data: dict, key: str, path: Path) -> time:
    value = data.get(key, _DEFAULTS[key])
    if not isinstance(value, str):
        raise ConfigError(f"{path}: '{key}' has the wrong type")
    if not _TIME_RE.match(value):
        raise ConfigError(f"{path}: '{key}' is invalid")
    return time(int(value[:2]), int(value[3:]))


def load_artemisa_campaign(path: Path) -> ArtemisaCampaign:
    path = Path(path)
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError:
        raise ConfigError(f"{path}: invalid TOML")

    for key in data:
        if key not in _TOP_KEYS:
            raise ConfigError(f"{path}: unknown key '{key}'")
    for key in _REQUIRED_TOP:
        if key not in data:
            raise ConfigError(f"{path}: missing key '{key}'")
    for table_name, table_keys in (("phrases", _PHRASES_KEYS), ("test_sample", _TEST_SAMPLE_KEYS)):
        if table_name not in data:
            raise ConfigError(f"{path}: missing key '{table_name}'")
        table = data[table_name]
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: '{table_name}' has the wrong type")
        for key in table:
            if key not in table_keys:
                raise ConfigError(f"{path}: unknown key '{table_name}.{key}'")
        for key in table_keys:
            if key not in table:
                raise ConfigError(f"{path}: missing key '{table_name}.{key}'")

    name = data["name"]
    if not isinstance(name, str):
        raise ConfigError(f"{path}: 'name' has the wrong type")
    if not _NAME_RE.match(name):
        raise ConfigError(f"{path}: 'name' is invalid")

    template = data["template"]
    if not isinstance(template, str):
        raise ConfigError(f"{path}: 'template' has the wrong type")
    if not template:
        raise ConfigError(f"{path}: 'template' is invalid")

    images = data["images"]
    if not isinstance(images, list) or not all(isinstance(item, str) for item in images):
        raise ConfigError(f"{path}: 'images' has the wrong type")
    if not 1 <= len(images) <= 3 or any(not item for item in images):
        raise ConfigError(f"{path}: 'images' is invalid")

    timezone = data.get("timezone", _DEFAULTS["timezone"])
    if not isinstance(timezone, str):
        raise ConfigError(f"{path}: 'timezone' has the wrong type")
    try:
        ZoneInfo(timezone)
    except Exception:
        raise ConfigError(f"{path}: 'timezone' is invalid")

    hourly_cap = _int_in(data, "hourly_cap", 1, 100, path)
    daily_cap = _int_in(data, "daily_cap", 1, 500, path)

    send_days = data.get("send_days", _DEFAULTS["send_days"])
    if not isinstance(send_days, list) or not all(isinstance(day, str) for day in send_days):
        raise ConfigError(f"{path}: 'send_days' has the wrong type")
    if not send_days or len(set(send_days)) != len(send_days) or any(day not in _DAYS for day in send_days):
        raise ConfigError(f"{path}: 'send_days' is invalid")

    send_start = _time_value(data, "send_start", path)
    send_end = _time_value(data, "send_end", path)
    if not send_end > send_start:
        raise ConfigError(f"{path}: 'send_end' is invalid")

    threshold = data.get("bounce_pause_threshold", _DEFAULTS["bounce_pause_threshold"])
    if not _is_number(threshold):
        raise ConfigError(f"{path}: 'bounce_pause_threshold' has the wrong type")
    if not 0 < threshold < 0.2:
        raise ConfigError(f"{path}: 'bounce_pause_threshold' is invalid")

    bounce_min_sends = _int_in(data, "bounce_min_sends", 1, 500, path)
    temporary_failure_limit = _int_in(data, "temporary_failure_limit", 1, 10, path)

    phrase_values: dict[str, str] = {}
    for key in _PHRASES_KEYS:
        value = _check_string(f"phrases.{key}", data["phrases"][key], path)
        error = ConfigError(f"{path}: 'phrases.{key}' is invalid")
        if _fields(value, error) != _PHRASE_FIELDS[key]:
            raise error
        phrase_values[key] = value
    nombre = _check_string("test_sample.nombre", data["test_sample"]["nombre"], path)

    return ArtemisaCampaign(
        name=name,
        template=Path(template),
        images=tuple(Path(item) for item in images),
        timezone=timezone,
        hourly_cap=hourly_cap,
        daily_cap=daily_cap,
        send_days=tuple(send_days),
        send_start=send_start,
        send_end=send_end,
        bounce_pause_threshold=float(threshold),
        bounce_min_sends=bounce_min_sends,
        temporary_failure_limit=temporary_failure_limit,
        phrases=ArtemisaPhrases(**phrase_values),
        test_sample=ArtemisaTestSample(nombre=nombre),
    )


def load_artemisa_template(path: Path, opt_out: str) -> Template:
    path = Path(path)
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    match = re.match(r"^Asunto: (.+)$", lines[0]) if lines else None
    if not match:
        raise ConfigError(f"{path}: line 1 must be 'Asunto: <subject>'")
    subject = match.group(1)
    if len(lines) < 2 or lines[1] != "":
        raise ConfigError(f"{path}: line 2 must be empty")
    body_lines = lines[2:]
    while body_lines and body_lines[-1] == "":
        body_lines.pop()
    body = "\n".join(body_lines)
    if not body:
        raise ConfigError(f"{path}: body is empty")

    braces = ConfigError(f"{path}: invalid braces")
    for name in _fields(subject, braces):
        raise ConfigError(f"{path}: unknown placeholder '{name}'")
    for name in _fields(body, braces):
        if name not in BODY_PLACEHOLDERS:
            raise ConfigError(f"{path}: unknown placeholder '{name}'")
    if HTML_PATTERN.search(subject) or HTML_PATTERN.search(body):
        raise ConfigError(f"{path}: HTML not allowed in template")
    if opt_out.strip() and opt_out.strip() in body:
        raise ConfigError(f"{path}: remove the opt-out sentence; it is added automatically")
    return Template(subject=subject, body=body)


def render_artemisa(tmpl: Template, phrases: ArtemisaPhrases, *, to: str, contact_id: int | None,
                    first_name: str, sender_name: str) -> RenderedEmail:
    nombre = _first_name(first_name)
    saludo = phrases.greeting_with_name.format(nombre=nombre) if nombre else phrases.greeting_without_name
    body = tmpl.body.format(saludo=saludo, remitente=sender_name) + "\n\n" + phrases.opt_out + "\n"
    return RenderedEmail(contact_id=contact_id, to=to, subject=tmpl.subject, body=body)
