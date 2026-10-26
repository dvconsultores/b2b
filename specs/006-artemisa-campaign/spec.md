# Feature Specification: Artemisa P2P Founders Campaign

**Feature Branch**: `006-artemisa-campaign`

**Created**: 2026-10-25

**Status**: Implemented 2026-10-25 (user request: "make all for this"); Telegram check removed the same day ("forget the phone")

**Input**: "In contactos/artemisa.csv I need to send emails offering Artemisa, with images 27 and
43. I will send from a normal Gmail account (daily limit about 500; we have 341 rows). Also tell me
whether those phone numbers are reachable from Telegram for direct messages [dropped later:
"forget the phone"]. New campaign, with
this text: *Se fundador, monta tu oferta, artemisa P2P es descentralizada y con reglas claras,
conectas tu wallet the Telegram y operas, sin custodia, sin letras pequeñas, ingresa en
@artemisa_p2p_bot*. I will provide the Gmail account later in .env
(`ARTEMISA_GMAIL_USER`, `ARTEMISA_GMAIL_PASS`, `ARTEMISA_GMAIL_FROM_NAME`)."

## Context

`contactos/artemisa.csv` is an export of Artemisa P2P's own KYC-verified users (340 data rows,
UTF-8 with BOM), not the B2B client lists of specs 001–005. Headers:
`user_id,email,first_name,last_name,kyc_full_name,nickname,phone,status_kyc,paypal_offers,types,first_offer,last_offer`.
Aggregates: 340 unique, syntactically valid emails (323 gmail.com); 340 phones written as
`'+<country> <number>` (Excel text marker), 299 of them Venezuelan `+58`; `status_kyc` is
`Verificado` for every row; `types` is `SELL` or `BUY,SELL`; `first_name` is never empty.
`contactos/27.png` and `contactos/43.png` are 1080×1080 Artemisa P2P creatives ("Comerciantes
fundadores — Llegar primero no se repite" and "Cambia USDT ↔ PayPal en minutos"), both carrying
`t.me/artemisa_p2p_bot`.

This is a different product (Artemisa P2P), audience (the platform's own users, who gave their
email and phone when registering) and sender (a Gmail account) from the nómina outreach. The
constitution is amended (1.5.0) to scope principles I and III and the SES constraint to the B2B
nómina campaigns and to admit this campaign's HTML body with inline images, Telegram handle and
Gmail sender.

## User Scenarios & Testing

### US1 — Import the Artemisa list into its own tracker (P1)

The operator runs `python -m b2b.send_artemisa --mode import`. The CSV is read into a separate
database `data/artemisa.sqlite3` (never into `data/b2b.sqlite3`). Only `user_id`, `email`,
`first_name`, `nickname` and `types` are stored (phones are not needed and not kept). Rows with an
invalid email or `user_id` are rejected and counted. The import is repeatable and never touches
tracking columns.

**Acceptance**: counts only are printed (rows read, new, updated, unchanged, rejected by reason);
a second import of the same file reports 0 new; a contact's `times_contacted`, `bounced`,
`opted_out` survive a re-import.

### US2 — Preview and test the email (P1)

`--mode preview` writes every pending email (To, Subject, plain body) to `data/previews/`.
`--mode test` sends the real multipart email (plain text + HTML with the two images inline) to
`TEST_RECIPIENTS` with the synthetic sample name and the subject prefixed `[PRUEBA]`.

**Acceptance**: the preview contains the user's text (typos corrected) and the opt-out line, no
HTML; the test message has `text/plain` and `text/html` alternatives and two inline PNG parts
referenced by `cid:` from the HTML; nothing is written to the tracker.

### US3 — Send once to every contact under Gmail's limits (P1)

`--mode send` sends from the Artemisa Gmail account (`smtp.gmail.com:465`, app password) to every
imported contact that has no attempt for this campaign, is not bounced and has not opted out:
one email per contact, at most `hourly_cap` per rolling hour and `daily_cap` per rolling 24 hours
(default 400, below Gmail's 500 for personal accounts), inside the send window; it waits for the
window and for the daily cap with `--wait-for-window`, otherwise it stops. Launch requires typing
the campaign name (or `--confirm`). Every attempt is recorded before the SMTP call; a run stops on
authentication/connection failures, Gmail throttling, three consecutive temporary failures, or a
permanent-rejection rate above the threshold.

**Acceptance**: with four synthetic contacts and `hourly_cap = 2`, the fake clock advances
between the second and third email; with `daily_cap = 3` the run stops with `daily_cap` (or
sleeps until the oldest attempt is 24 hours old with `--wait-for-window`); a second launch sends
nothing (`nothing_to_send`); an attempt left `pending` by a crash becomes `unknown` and is never
re-sent; the summary prints counts only.

## Requirements

- **FR-001**: New config `config/artemisa.toml` and template `config/templates/artemisa.txt`
  (plan D2, D3); the template body is the user's text with typos corrected.
- **FR-002**: New tracker `data/artemisa.sqlite3` with the same `runs` / `send_attempts` tables as
  spec 002 and an Artemisa `contacts` table (plan D4), so spec 002's tracking functions are reused.
- **FR-003**: `.env` keys `ARTEMISA_GMAIL_USER`, `ARTEMISA_GMAIL_PASS`, `ARTEMISA_GMAIL_FROM_NAME`
  (sender = user; host/port fixed to `smtp.gmail.com` / 465); `TEST_RECIPIENTS` reused.
- **FR-004**: Multipart message: `text/plain` + `text/html` alternative, images as inline
  `image/png` related parts with `Content-ID`, HTML built from the plain body (escaped), no
  tracking pixels, no external resources.
- **FR-005**: Hourly cap and rolling 24-hour daily cap, send window, confirmation gate, at-most-once
  attempts, pending recovery, stop kinds as spec 002.
- **FR-006**: No change to `send_first_email`, `campaign.toml`, `store.py` schema or the Docker
  entrypoint; the Artemisa campaign runs from this machine.

## Success Criteria

- **SC-001**: 340 contacts imported, 0 rejected (expected from the aggregates above).
- **SC-002**: A full send completes in one launch within one day under the default caps
  (40/hour, 400/day, window 09:00–21:00 America/Caracas, every day) without a Gmail limit error.
- **SC-003**: No contact receives the email twice, in any sequence of launches and crashes.

## Assumptions

- The Gmail account has 2-step verification and an app password; "less secure apps" is gone.
- Gmail may throttle a new or rarely used account below 500/day; the caps are config values the
  operator can lower (for example 20/hour, 150/day over three days).
- Recipients registered on Artemisa P2P with this email and phone; the message is a product
  announcement from the platform, with an opt-out line.

  limits and bans accounts that do it. The check only measures reachability.
