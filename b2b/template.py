"""Template loading, company/name formatting and email rendering."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path

from b2b import ConfigError
from b2b.campaign import HTML_PATTERN, LINK_PATTERN, Phrases, contains_link_or_html

SUBJECT_PLACEHOLDERS = frozenset({"empresa"})
BODY_PLACEHOLDERS = frozenset({"saludo", "apertura", "remitente"})
HONORIFICS = frozenset(
    {
        "ing",
        "lic",
        "licda",
        "dr",
        "dra",
        "sr",
        "sra",
        "srta",
        "abg",
        "arq",
        "econ",
        "prof",
        "msc",
        "mba",
        "tsu",
    }
)

_LEGAL_SUFFIXES = {"ca": "C.A.", "sa": "S.A.", "srl": "S.R.L.", "cia": "Cía."}
_LOWERCASE_WORDS = {"de", "del", "la", "las", "los", "y", "e", "en"}
_VOWELS = "aeiouáéíóú"
_LEADING_CHARS = "(¿¡\""
_TRAILING_CHARS = ",;:)!?\""


@dataclass(frozen=True)
class Template:
    subject: str
    body: str


@dataclass(frozen=True)
class RenderedEmail:
    contact_id: int | None
    to: str
    subject: str
    body: str


def _fields(text: str, path: Path) -> list[str]:
    names: list[str] = []
    try:
        for _, name, format_spec, conversion in string.Formatter().parse(text):
            if name is None:
                continue
            if format_spec or conversion:
                raise ConfigError(f"{path}: invalid braces")
            names.append(name)
    except ValueError:
        raise ConfigError(f"{path}: invalid braces") from None
    return names


def load_template(path: Path, opt_out: str) -> Template:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")

    if not lines or not (match := _subject_match(lines[0])):
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

    for name in _fields(subject, path):
        if name not in SUBJECT_PLACEHOLDERS:
            raise ConfigError(f"{path}: unknown placeholder '{name}'")
    for name in _fields(body, path):
        if name not in BODY_PLACEHOLDERS:
            raise ConfigError(f"{path}: unknown placeholder '{name}'")

    if LINK_PATTERN.search(subject) or LINK_PATTERN.search(body):
        raise ConfigError(f"{path}: link or domain not allowed in template")
    if HTML_PATTERN.search(subject) or HTML_PATTERN.search(body):
        raise ConfigError(f"{path}: HTML not allowed in template")
    if opt_out.strip() and opt_out.strip() in body:
        raise ConfigError(f"{path}: remove the opt-out sentence; it is added automatically")

    return Template(subject=subject, body=body)


def _subject_match(line: str):
    return re.match(r"^Asunto: (.+)$", line)


def display_company(company: str, fallback: str) -> str:
    stripped = company.strip()
    if not stripped:
        return fallback
    if not any(c.isalpha() for c in stripped):
        return stripped
    if any(c.islower() for c in stripped):
        return stripped

    words = stripped.split(" ")
    result: list[str] = []
    for i, word in enumerate(words):
        leading = ""
        trailing = ""
        start = 0
        while start < len(word) and word[start] in _LEADING_CHARS:
            leading += word[start]
            start += 1
        end = len(word)
        while end > start and word[end - 1] in _TRAILING_CHARS:
            end -= 1
        trailing = word[end:]
        middle = word[start:end]

        key = "".join(c for c in middle if c.isalpha()).casefold()
        letters = [c for c in middle if c.isalpha()]

        if key in _LEGAL_SUFFIXES:
            middle = _LEGAL_SUFFIXES[key]
        elif i > 0 and middle.casefold() in _LOWERCASE_WORDS:
            middle = middle.lower()
        elif 2 <= len(letters) <= 4 and not any(c.casefold() in _VOWELS for c in letters):
            middle = middle
        else:
            middle = middle[:1].upper() + middle[1:].lower()

        result.append(leading + middle + trailing)
    return " ".join(result)


def first_name(contact_name: str) -> str:
    tokens = contact_name.split()
    remaining = [t for t in tokens if "".join(c for c in t if c.isalpha()).casefold() not in HONORIFICS]
    if not remaining:
        return ""
    token = remaining[0].rstrip(",.")
    if not token:
        return ""
    if any(c.isdigit() for c in token) or "@" in token:
        return ""
    if any(c.isalpha() for c in token) and not any(c.islower() for c in token):
        return token[:1].upper() + token[1:].lower()
    return token


def render(
    template: Template,
    phrases: Phrases,
    *,
    to: str,
    contact_id: int | None,
    company: str,
    contact_name: str,
    city: str,
    sender_name: str,
) -> RenderedEmail:
    empresa = display_company(company, phrases.company_fallback)
    nombre = first_name(contact_name)
    if nombre:
        saludo = phrases.greeting_with_name.format(nombre=nombre)
    else:
        saludo = phrases.greeting_without_name
    if city.strip():
        apertura = phrases.opening_with_city.format(empresa=empresa, ciudad=city.strip())
    else:
        apertura = phrases.opening_without_city.format(empresa=empresa)
    subject = template.subject.format(empresa=empresa)
    body = (
        template.body.format(saludo=saludo, apertura=apertura, remitente=sender_name)
        + "\n\n"
        + phrases.opt_out
        + "\n"
    )
    return RenderedEmail(contact_id=contact_id, to=to, subject=subject, body=body)


def rendered_has_link(email: RenderedEmail) -> bool:
    return contains_link_or_html(email.subject) or contains_link_or_html(email.body)
