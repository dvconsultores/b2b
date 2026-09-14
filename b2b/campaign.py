from __future__ import annotations

import re
import string
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from b2b import ConfigError

LINK_PATTERN: re.Pattern[str] = re.compile(
    r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|ve|co|io|info|biz|app|dev|me)\b)",
    re.IGNORECASE,
)
HTML_PATTERN: re.Pattern[str] = re.compile(r"(</?[a-z][^>]*>|&[a-z]+;)", re.IGNORECASE)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_TOP_KEYS = (
    "name",
    "step",
    "template",
    "launch_price_end",
    "timezone",
    "hourly_cap",
    "batch_limit",
    "send_days",
    "send_start",
    "send_end",
    "bounce_pause_threshold",
    "bounce_min_sends",
    "temporary_failure_limit",
    "test_sample_count",
    "phrases",
    "test_sample",
)
_REQUIRED_TOP = ("name", "template", "launch_price_end")
_PHRASES_KEYS = (
    "greeting_with_name",
    "greeting_without_name",
    "opening_with_city",
    "opening_without_city",
    "company_fallback",
    "opt_out",
)
_TEST_SAMPLE_KEYS = ("nombre", "empresa", "ciudad")

_DEFAULTS = {
    "step": 1,
    "timezone": "America/Caracas",
    "hourly_cap": 20,
    "batch_limit": 100,
    "send_days": ["mon", "tue", "wed", "thu", "fri"],
    "send_start": "08:00",
    "send_end": "17:00",
    "bounce_pause_threshold": 0.02,
    "bounce_min_sends": 20,
    "temporary_failure_limit": 3,
    "test_sample_count": 3,
}

_PHRASE_FIELDS = {
    "greeting_with_name": {"nombre"},
    "greeting_without_name": set(),
    "opening_with_city": {"empresa", "ciudad"},
    "opening_without_city": {"empresa"},
    "company_fallback": set(),
    "opt_out": set(),
}


def contains_link_or_html(text: str) -> bool:
    return bool(LINK_PATTERN.search(text) or HTML_PATTERN.search(text))


@dataclass(frozen=True)
class Phrases:
    greeting_with_name: str
    greeting_without_name: str
    opening_with_city: str
    opening_without_city: str
    company_fallback: str
    opt_out: str


@dataclass(frozen=True)
class TestSample:
    nombre: str
    empresa: str
    ciudad: str


@dataclass(frozen=True)
class Campaign:
    name: str
    step: int
    template: Path
    launch_price_end: date
    timezone: str
    hourly_cap: int
    batch_limit: int
    send_days: tuple[str, ...]
    send_start: time
    send_end: time
    bounce_pause_threshold: float
    bounce_min_sends: int
    temporary_failure_limit: int
    test_sample_count: int
    phrases: Phrases
    test_sample: TestSample


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_float(value: object) -> bool:
    return isinstance(value, float) and not isinstance(value, bool)


def _check_placeholders(key: str, text: str, expected: set[str], path: Path) -> None:
    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError:
        raise ConfigError(f"{path}: '{key}' is invalid")
    fields: set[str] = set()
    for _literal, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if conversion is not None or format_spec:
            raise ConfigError(f"{path}: '{key}' is invalid")
        fields.add(field_name)
    if fields != expected:
        raise ConfigError(f"{path}: '{key}' is invalid")


def _check_string(key: str, value: object, path: Path) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{path}: '{key}' has the wrong type")
    if contains_link_or_html(value):
        raise ConfigError(f"{path}: '{key}' contains a link or HTML")
    return value


def load_campaign(path: Path) -> Campaign:
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

    for table_name, table_keys in (
        ("phrases", _PHRASES_KEYS),
        ("test_sample", _TEST_SAMPLE_KEYS),
    ):
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

    step = data.get("step", _DEFAULTS["step"])
    if not _is_int(step):
        raise ConfigError(f"{path}: 'step' has the wrong type")
    if step != 1:
        raise ConfigError(f"{path}: 'step' is invalid")

    template = data["template"]
    if not isinstance(template, str):
        raise ConfigError(f"{path}: 'template' has the wrong type")
    if not template:
        raise ConfigError(f"{path}: 'template' is invalid")
    template_path = Path(template)

    launch_price_end = data["launch_price_end"]
    if isinstance(launch_price_end, datetime) or not isinstance(launch_price_end, date):
        raise ConfigError(f"{path}: 'launch_price_end' has the wrong type")

    timezone = data.get("timezone", _DEFAULTS["timezone"])
    if not isinstance(timezone, str):
        raise ConfigError(f"{path}: 'timezone' has the wrong type")
    try:
        ZoneInfo(timezone)
    except Exception:
        raise ConfigError(f"{path}: 'timezone' is invalid")

    hourly_cap = data.get("hourly_cap", _DEFAULTS["hourly_cap"])
    if not _is_int(hourly_cap):
        raise ConfigError(f"{path}: 'hourly_cap' has the wrong type")
    if not 1 <= hourly_cap <= 60:
        raise ConfigError(f"{path}: 'hourly_cap' is invalid")

    batch_limit = data.get("batch_limit", _DEFAULTS["batch_limit"])
    if not _is_int(batch_limit):
        raise ConfigError(f"{path}: 'batch_limit' has the wrong type")
    if not 1 <= batch_limit <= 500:
        raise ConfigError(f"{path}: 'batch_limit' is invalid")

    send_days = data.get("send_days", _DEFAULTS["send_days"])
    if not isinstance(send_days, list) or not all(
        isinstance(day, str) for day in send_days
    ):
        raise ConfigError(f"{path}: 'send_days' has the wrong type")
    if not send_days:
        raise ConfigError(f"{path}: 'send_days' is invalid")
    if len(set(send_days)) != len(send_days):
        raise ConfigError(f"{path}: 'send_days' is invalid")
    if any(day not in _DAYS for day in send_days):
        raise ConfigError(f"{path}: 'send_days' is invalid")
    send_days_tuple = tuple(send_days)

    send_start = data.get("send_start", _DEFAULTS["send_start"])
    if not isinstance(send_start, str):
        raise ConfigError(f"{path}: 'send_start' has the wrong type")
    if not _TIME_RE.match(send_start):
        raise ConfigError(f"{path}: 'send_start' is invalid")
    send_start_time = time(int(send_start[:2]), int(send_start[3:]))

    send_end = data.get("send_end", _DEFAULTS["send_end"])
    if not isinstance(send_end, str):
        raise ConfigError(f"{path}: 'send_end' has the wrong type")
    if not _TIME_RE.match(send_end):
        raise ConfigError(f"{path}: 'send_end' is invalid")
    send_end_time = time(int(send_end[:2]), int(send_end[3:]))
    if not send_end_time > send_start_time:
        raise ConfigError(f"{path}: 'send_end' is invalid")

    bounce_pause_threshold = data.get(
        "bounce_pause_threshold", _DEFAULTS["bounce_pause_threshold"]
    )
    if not (_is_int(bounce_pause_threshold) or _is_float(bounce_pause_threshold)):
        raise ConfigError(f"{path}: 'bounce_pause_threshold' has the wrong type")
    if not 0 < bounce_pause_threshold < 0.2:
        raise ConfigError(f"{path}: 'bounce_pause_threshold' is invalid")
    bounce_pause_threshold = float(bounce_pause_threshold)

    bounce_min_sends = data.get("bounce_min_sends", _DEFAULTS["bounce_min_sends"])
    if not _is_int(bounce_min_sends):
        raise ConfigError(f"{path}: 'bounce_min_sends' has the wrong type")
    if not 1 <= bounce_min_sends <= 500:
        raise ConfigError(f"{path}: 'bounce_min_sends' is invalid")

    temporary_failure_limit = data.get(
        "temporary_failure_limit", _DEFAULTS["temporary_failure_limit"]
    )
    if not _is_int(temporary_failure_limit):
        raise ConfigError(f"{path}: 'temporary_failure_limit' has the wrong type")
    if not 1 <= temporary_failure_limit <= 10:
        raise ConfigError(f"{path}: 'temporary_failure_limit' is invalid")

    test_sample_count = data.get("test_sample_count", _DEFAULTS["test_sample_count"])
    if not _is_int(test_sample_count):
        raise ConfigError(f"{path}: 'test_sample_count' has the wrong type")
    if not 1 <= test_sample_count <= 3:
        raise ConfigError(f"{path}: 'test_sample_count' is invalid")

    phrases_table = data["phrases"]
    phrase_values: dict[str, str] = {}
    for key in _PHRASES_KEYS:
        value = _check_string(f"phrases.{key}", phrases_table[key], path)
        _check_placeholders(f"phrases.{key}", value, _PHRASE_FIELDS[key], path)
        phrase_values[key] = value
    phrases = Phrases(**phrase_values)

    test_sample_table = data["test_sample"]
    test_sample_values: dict[str, str] = {}
    for key in _TEST_SAMPLE_KEYS:
        test_sample_values[key] = _check_string(
            f"test_sample.{key}", test_sample_table[key], path
        )
    test_sample = TestSample(**test_sample_values)

    return Campaign(
        name=name,
        step=step,
        template=template_path,
        launch_price_end=launch_price_end,
        timezone=timezone,
        hourly_cap=hourly_cap,
        batch_limit=batch_limit,
        send_days=send_days_tuple,
        send_start=send_start_time,
        send_end=send_end_time,
        bounce_pause_threshold=bounce_pause_threshold,
        bounce_min_sends=bounce_min_sends,
        temporary_failure_limit=temporary_failure_limit,
        test_sample_count=test_sample_count,
        phrases=phrases,
        test_sample=test_sample,
    )
