"""Spec 006 plan D2, D3: Artemisa campaign config, template and rendering."""
from datetime import time
from pathlib import Path

import pytest

from b2b import ConfigError
from b2b.artemisa_config import load_artemisa_campaign, load_artemisa_template, render_artemisa

ROOT = Path(__file__).resolve().parents[1]

MINIMAL = """\
name = "artemisa-prueba"
template = "config/templates/artemisa.txt"
images = ["a.png"]

[phrases]
greeting_with_name = "Hola {nombre},"
greeting_without_name = "Hola,"
opt_out = "Responde no y no te escribimos más."

[test_sample]
nombre = "ANA"
"""

TEMPLATE = """\
Asunto: Sé fundador en Artemisa P2P

{saludo}

Monta tu oferta en t.me/artemisa_p2p_bot.

Saludos,
{remitente}
"""


def write(tmp_path, text, name="artemisa.toml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_real_config_and_template_load():
    campaign = load_artemisa_campaign(ROOT / "config" / "artemisa.toml")
    assert campaign.name == "artemisa-fundadores-2026"
    assert campaign.daily_cap <= 500 and campaign.hourly_cap <= 100
    assert [p.name for p in campaign.images] == ["27.png", "43.png"]
    template = load_artemisa_template(ROOT / campaign.template, campaign.phrases.opt_out)
    assert "@artemisa_p2p_bot" in template.body
    assert "{saludo}" in template.body and "{remitente}" in template.body


def test_defaults(tmp_path):
    campaign = load_artemisa_campaign(write(tmp_path, MINIMAL))
    assert (campaign.timezone, campaign.hourly_cap, campaign.daily_cap) == ("America/Caracas", 40, 400)
    assert campaign.send_days == ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    assert (campaign.send_start, campaign.send_end) == (time(9, 0), time(21, 0))
    assert (campaign.bounce_pause_threshold, campaign.bounce_min_sends, campaign.temporary_failure_limit) == (0.05, 20, 3)
    assert campaign.step == 1
    assert campaign.images == (Path("a.png"),)
    assert campaign.test_sample.nombre == "ANA"


@pytest.mark.parametrize("change, message", [
    ("name = \"artemisa-prueba\"\nstep = 1", "unknown key 'step'"),
    ("name = \"artemisa-prueba\"\n", "missing key 'name'"),
    ("images = [\"a.png\"]\n", "missing key 'images'"),
    ("images = [\"a.png\"]\nimages = []", "'images' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\", \"b.png\", \"c.png\", \"d.png\"]", "'images' is invalid"),
    ("images = [\"a.png\"]\nimages = \"a.png\"", "'images' has the wrong type"),
    ("name = \"artemisa-prueba\"\nname = \"Mal Nombre\"", "'name' is invalid"),
    ("name = \"artemisa-prueba\"\nname = 3", "'name' has the wrong type"),
    ("template = \"config/templates/artemisa.txt\"\ntemplate = \"\"", "'template' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nhourly_cap = 0", "'hourly_cap' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nhourly_cap = 101", "'hourly_cap' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nhourly_cap = true", "'hourly_cap' has the wrong type"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\ndaily_cap = 501", "'daily_cap' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\ntimezone = \"Marte/Base\"", "'timezone' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nsend_days = []", "'send_days' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nsend_days = [\"mon\", \"mon\"]", "'send_days' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nsend_start = \"9:00\"", "'send_start' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nsend_start = \"21:00\"\nsend_end = \"09:00\"", "'send_end' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nbounce_pause_threshold = 0.2", "'bounce_pause_threshold' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\nbounce_min_sends = 0", "'bounce_min_sends' is invalid"),
    ("images = [\"a.png\"]\nimages = [\"a.png\"]\ntemporary_failure_limit = 11", "'temporary_failure_limit' is invalid"),
    ("greeting_with_name = \"Hola {nombre},\"", "missing key 'phrases.greeting_with_name'"),
    ("greeting_with_name = \"Hola {nombre},\"\ngreeting_with_name = \"Hola,\"", "'phrases.greeting_with_name' is invalid"),
    ("greeting_without_name = \"Hola,\"\ngreeting_without_name = \"Hola {nombre},\"", "'phrases.greeting_without_name' is invalid"),
    ("greeting_without_name = \"Hola,\"\ngreeting_without_name = \"<b>Hola</b>\"", "'phrases.greeting_without_name' contains HTML"),
    ("greeting_without_name = \"Hola,\"\ngreeting_without_name = 5", "'phrases.greeting_without_name' has the wrong type"),
    ("nombre = \"ANA\"", "missing key 'test_sample.nombre'"),
    ("nombre = \"ANA\"\nnombre = \"<i>Ana</i>\"", "'test_sample.nombre' contains HTML"),
    ("nombre = \"ANA\"\nextra = 1", "unknown key 'test_sample.extra'"),
])
def test_invalid_config(tmp_path, change, message):
    old, _, new = change.partition("\n")
    text = MINIMAL.replace(old + "\n", (new + "\n") if new else "", 1)
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as excinfo:
        load_artemisa_campaign(path)
    assert str(excinfo.value) == f"{path}: {message}"


def test_missing_tables(tmp_path):
    path = write(tmp_path, MINIMAL.replace('[test_sample]\nnombre = "ANA"\n', ""))
    with pytest.raises(ConfigError, match="missing key 'test_sample'"):
        load_artemisa_campaign(path)
    path = write(tmp_path, MINIMAL.replace("[phrases]", "phrases = 1\n[x]"))
    with pytest.raises(ConfigError, match="unknown key 'x'"):
        load_artemisa_campaign(path)


def test_links_allowed_in_phrases(tmp_path):
    text = MINIMAL.replace('opt_out = "Responde no y no te escribimos más."',
                           'opt_out = "Escríbenos en t.me/artemisa_p2p_bot si no quieres más correos."')
    assert "t.me" in load_artemisa_campaign(write(tmp_path, text)).phrases.opt_out


def test_invalid_toml(tmp_path):
    path = write(tmp_path, "name = [\n")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_artemisa_campaign(path)


def test_template_loads_with_link(tmp_path):
    template = load_artemisa_template(write(tmp_path, TEMPLATE, "t.txt"), "Responde no.")
    assert template.subject == "Sé fundador en Artemisa P2P"
    assert template.body.startswith("{saludo}\n\nMonta tu oferta en t.me/artemisa_p2p_bot.")
    assert template.body.endswith("{remitente}")


@pytest.mark.parametrize("text, message", [
    ("Hola\n\nCuerpo\n", "line 1 must be 'Asunto: <subject>'"),
    ("Asunto: Hola\nCuerpo\n", "line 2 must be empty"),
    ("Asunto: Hola\n\n\n\n", "body is empty"),
    ("Asunto: Hola {empresa}\n\nCuerpo\n", "unknown placeholder 'empresa'"),
    ("Asunto: Hola\n\n{apertura}\n", "unknown placeholder 'apertura'"),
    ("Asunto: Hola\n\n{saludo:>10}\n", "invalid braces"),
    ("Asunto: Hola\n\nCuerpo {\n", "invalid braces"),
    ("Asunto: Hola\n\n<b>Cuerpo</b>\n", "HTML not allowed in template"),
    ("Asunto: Hola\n\nCuerpo\n\nResponde no.\n", "remove the opt-out sentence; it is added automatically"),
])
def test_invalid_template(tmp_path, text, message):
    path = write(tmp_path, text, "t.txt")
    with pytest.raises(ConfigError) as excinfo:
        load_artemisa_template(path, "Responde no.")
    assert str(excinfo.value) == f"{path}: {message}"


def test_render_with_and_without_name(tmp_path):
    campaign = load_artemisa_campaign(write(tmp_path, MINIMAL))
    template = load_artemisa_template(write(tmp_path, TEMPLATE, "t.txt"), campaign.phrases.opt_out)
    email = render_artemisa(template, campaign.phrases, to="ana@example.com", contact_id=7,
                            first_name="CARLOS", sender_name="Artemisa P2P")
    assert (email.contact_id, email.to, email.subject) == (7, "ana@example.com", "Sé fundador en Artemisa P2P")
    assert email.body == ("Hola Carlos,\n\nMonta tu oferta en t.me/artemisa_p2p_bot.\n\nSaludos,\nArtemisa P2P"
                          "\n\nResponde no y no te escribimos más.\n")
    anonymous = render_artemisa(template, campaign.phrases, to="x@example.com", contact_id=None,
                                first_name="", sender_name="Artemisa P2P")
    assert anonymous.body.startswith("Hola,\n\n")
    assert render_artemisa(template, campaign.phrases, to="x@example.com", contact_id=None,
                           first_name="ING. MARÍA JOSÉ", sender_name="A").body.startswith("Hola María,")
