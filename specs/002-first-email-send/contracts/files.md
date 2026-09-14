# Contract: campaign, template, preview and environment files

**Feature**: 002-first-email-send

## `config/campaign.toml` (operator-editable, no personal data)

All keys required unless a default is given. Unknown keys are an error.

| Key | Type | Default | Rule |
|-----|------|---------|------|
| `name` | string | — | `^[a-z0-9][a-z0-9-]{2,49}$`; stored in `send_attempts.campaign` |
| `step` | integer | `1` | must be 1 |
| `template` | string | — | path to the template, relative to the project root |
| `launch_price_end` | date | — | TOML date, e.g. `2026-12-31` |
| `timezone` | string | `"America/Caracas"` | valid `zoneinfo` name |
| `hourly_cap` | integer | `20` | 1–60 |
| `batch_limit` | integer | `100` | 1–500 |
| `send_days` | array of strings | `["mon","tue","wed","thu","fri"]` | non-empty subset of `mon tue wed thu fri sat sun`, no repeats |
| `send_start` | string | `"08:00"` | `HH:MM`, 24-hour |
| `send_end` | string | `"17:00"` | `HH:MM`, later than `send_start` |
| `bounce_pause_threshold` | float | `0.02` | 0 < value < 0.2 |
| `bounce_min_sends` | integer | `20` | 1–500 |
| `temporary_failure_limit` | integer | `3` | 1–10 |
| `test_sample_count` | integer | `3` | 1–3 |
| `[phrases].greeting_with_name` | string | — | must contain `{nombre}` and no other placeholder |
| `[phrases].greeting_without_name` | string | — | no placeholder |
| `[phrases].opening_with_city` | string | — | must contain `{empresa}` and `{ciudad}` only |
| `[phrases].opening_without_city` | string | — | must contain `{empresa}` only |
| `[phrases].company_fallback` | string | — | no placeholder |
| `[phrases].opt_out` | string | — | no placeholder |
| `[test_sample].nombre` | string | — | synthetic person name |
| `[test_sample].empresa` | string | — | synthetic company name |
| `[test_sample].ciudad` | string | — | public city name |

All strings: no link or HTML (plan D5 patterns).

Initial content:

```toml
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
opt_out = "P. D.: Si no es de su interés, responda \"no\" y no le vuelvo a escribir."

[test_sample]
nombre = "ANA PÉREZ"
empresa = "EMPRESA EJEMPLO, C.A."
ciudad = "Caracas"
```

## `config/templates/primer_contacto.txt` (operator-editable)

- UTF-8, `\n` line endings. Line 1: `Asunto: <subject>`. Line 2: empty. Lines 3+: body, one line
  per paragraph, blank line between paragraphs. Trailing blank lines are removed.
- Placeholders: subject `{empresa}`; body `{saludo}`, `{apertura}`, `{remitente}`.
- Must not contain links, HTML, other placeholders, or the opt-out sentence (it is appended).

Initial content:

```text
Asunto: Pregunta rápida sobre la nómina de {empresa}

{saludo}

{apertura}

Con Nómina Atenea las empresas dejan de perder horas cada quincena y evitan errores en los pagos. Además, mantenemos el precio de lanzamiento durante todo el año, con la mejor relación precio-calidad del mercado.

¿Le interesa que le cuente cómo funciona? Con responder "sí" es suficiente.

Saludos,
{remitente}
```

Rendered body = template body with placeholders filled + `\n\n` + `phrases.opt_out` + `\n`.

## `data/previews/<campaign>-<YYYYMMDD-HHMMSS>.txt` (generated — REAL CONTACT DATA)

UTF-8. Timestamp in the campaign time zone.

```text
Campaign: primer-contacto-2026 (step 1)
Generated: 2026-09-14 09:00 America/Caracas
Emails: <n>

===== 1 of <n> =====
To: <address>
Subject: <subject>

<body>

===== 2 of <n> =====
...
```

## `.env` keys used by this feature

| Key | Used for | Rule |
|-----|----------|------|
| `HOST_EMAIL` | SMTP host | non-empty |
| `PORT_EMAIL` | SMTP port | 465 or 587 |
| `USER_EMAIL` | SMTP username | non-empty |
| `PASS_EMAIL` | SMTP password | non-empty |
| `SENDER_EMAIL` | From address, envelope sender, Reply-To, preflight domain | valid address |
| `SMTP_FROM_NAME` | From display name and `{remitente}` | non-empty, no link or HTML |
| `TEST_RECIPIENTS` | test mode only | comma-separated, 1–5 valid addresses (the operator's own) |

`TEST_RECIPIENTS` is new; the operator adds it before the first test run.
