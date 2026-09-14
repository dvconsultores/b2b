# Feature Specification: First Outreach Email and Sending

**Feature Branch**: `002-first-email-send` (feature directory; the project has no git)

**Created**: 2026-09-13

**Status**: Draft — clarified, ready for planning

**Input**: User description: "The click FOMO email send template as plain text in Spanish."
Scope agreed: template, deliverability preflight, dry run, test sends and throttled sending
that updates the contact database (docs/plan.md §3 Step 1, §6 Parts E and G).

**Depends on**: spec 001 (contact database with tracking fields). Bounce-based pausing uses
bounces recorded during sending or after the manual inbox check.

## Clarifications

### Session 2026-09-13

- Q: "Click FOMO" suggests a link, but the constitution forbids links in email #1. What is the
  first email? → A: Plain-text Spanish, no link. Urgency must be true. The call to action is a
  question answered by replying; the landing-page link is sent only after a reply.
- Q: Template only, or template plus sending? → A: Template, deliverability preflight, dry run
  by default, test sends to own addresses, and throttled production sending that updates the
  database.
- Q: Which true fact creates urgency? → A (revised): The launch price is kept for the whole
  year and is the best price–quality ratio on the market. The email states this without any
  price amount (prices live on the landing page, docs/plan.md §4), and nothing is sent after
  the launch-price year ends.
- Q: Is the SES account ready? → A: The operator confirmed on 2026-09-13 that DKIM is enabled
  for the domain, the account is out of the SES sandbox, bounce notices go to the sender
  address, and `.env` holds the production settings.
- Q: What if DMARC is still missing? → A: Production sending may be forced with an explicit
  option; the operator publishes DMARC and fixes SPF manually.
- Q: May further batches go out before inbox processing exists? → A: No. After the first
  production batch, the next waits until the operator has checked the inbox and recorded it with
  `mark_inbox_checked` (automatic processing, spec 003, deferred).
- Q: How do production runs happen? → A: Unattended in Docker on the server: one batch per launch
  at the hourly cap, waiting through nights and weekends, confirmed at launch with the campaign
  name; the container then stops and emails a counts-only summary to `TEST_RECIPIENTS`.
- Q: Who at a company gets the first email in a campaign? → A: One contact per company key per
  campaign.

## Deliverability Findings (DNS, 2026-09-13)

- Sender domain `dvconsultores.com` receives mail on Google Workspace; sending goes through
  Amazon SES (SMTP endpoint in `us-east-2`).
- The SPF record does not include Amazon SES.
- No DMARC record is published (`_dmarc.dvconsultores.com` is empty).
- SES DKIM for the domain: enabled (confirmed by the operator, 2026-09-13).
- SES account out of the sandbox, bounce notices to the sender address: confirmed by the
  operator, 2026-09-13.
- DMARC and SPF: the operator will fix them manually.

## Draft Template (Spanish, plain text)

Placeholders in braces. Wording is a draft for the operator to approve.

```text
Asunto: Pregunta rápida sobre la nómina de {empresa}

Hola {nombre},

Vi que {empresa} está en {ciudad} y quería hacerle una pregunta rápida:
¿todavía calculan la nómina a mano o en hojas de cálculo?

Con Nómina Atenea las empresas dejan de perder horas cada quincena y evitan
errores en los pagos. Además, mantenemos el precio de lanzamiento durante todo
el año, con la mejor relación precio-calidad del mercado.

¿Le interesa que le cuente cómo funciona? Con responder "sí" es suficiente.

Saludos,
{remitente}

P. D.: Si no es de su interés, responda "no" y no le vuelvo a escribir.
```

Fallbacks: no contact name → "Hola,"; no city → first line becomes "Quería hacerle una pregunta
rápida sobre la nómina de {empresa}:".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preview the first email without sending (Priority: P1)

The operator runs the send step in its default mode and gets every email the campaign would
send, fully personalized, in a file to read — and nothing is sent.

**Why this priority**: docs/plan.md Part H step 4 and Constitution principle V require a dry
run before any real email.

**Independent Test**: run the default mode against a synthetic database and check the preview
file and that no connection to the email provider was made.

**Acceptance Scenarios**:

1. **Given** eligible contacts, **When** the operator runs the send step without the send
   option, **Then** a preview file lists each recipient with the rendered subject and body,
   the screen shows only counts, and no email is sent and no contact is changed.
2. **Given** a contact with a name and a city, **When** rendered, **Then** the greeting uses
   the name and the first line uses the company and city.
3. **Given** a contact without a name or without a city, **When** rendered, **Then** the
   matching fallback text is used and no empty placeholder or stray punctuation remains.
4. **Given** a company name stored in capitals with a legal suffix (for example
   "INVERSIONES EJEMPLO, C.A."), **When** rendered, **Then** it reads naturally
   ("Inversiones Ejemplo, C.A.").
5. **Given** a template containing a web address, HTML markup or an attachment, **When** the
   step starts, **Then** it refuses to run and names the problem.

---

### User Story 2 - Test send to own addresses (Priority: P1)

The operator sends a few rendered emails to their own configured test addresses to see how
they look and land (inbox vs spam) in real mail clients.

**Why this priority**: docs/plan.md Part H step 5; catches rendering and deliverability
problems before any prospect is emailed.

**Independent Test**: run test mode with a simulated email provider and check that only test
addresses received messages and the database did not change.

**Acceptance Scenarios**:

1. **Given** configured test addresses, **When** the operator runs test mode, **Then** a sample
   of rendered emails is delivered only to those addresses, with a subject marker showing it
   is a test.
2. **Given** a test run, **When** it finishes, **Then** no contact's tracking fields changed.

---

### User Story 3 - Throttled production send (Priority: P1)

The operator confirms a batch and the system emails eligible contacts slowly, records every
send, and stops on its own if bounces climb.

**Why this priority**: this is the outreach itself; Constitution principles I and II govern it.

**Independent Test**: run a production send against a synthetic database and a simulated
provider (including permanent rejections and interruptions) and check recipients, pacing,
database updates and the pause rule.

**Acceptance Scenarios**:

1. **Given** the send option, **When** the step starts, **Then** it shows the campaign,
   recipient count, hourly cap and batch limit and sends nothing until the operator confirms.
2. **Given** a confirmed batch, **When** an email is accepted by the provider, **Then** that
   contact's times contacted increases by 1, last contacted is set, and a send-log entry is
   recorded.
3. **Given** a contact already emailed, bounced, responded or opted out, **When** eligibility is
   computed, **Then** the contact is not included.
4. **Given** the provider permanently rejects an address during sending, **When** it happens,
   **Then** the contact is marked bounced and the send log records the rejection.
5. **Given** the campaign's bounce rate exceeds 2% after at least 20 sends, **When** the next
   email is due, **Then** sending stops and the summary says why.
6. **Given** the run is interrupted (crash, network loss), **When** it is started again,
   **Then** no contact is emailed twice; any send with an unknown outcome is listed for review
   instead of being retried.
7. **Given** the hourly cap and batch limit, **When** the run proceeds, **Then** neither is ever
   exceeded.

---

### User Story 4 - Deliverability preflight (Priority: P2)

Before a production send, the system checks the sender domain's public mail records and shows
what is missing, so the first campaign does not start with avoidable spam-folder placement.

**Why this priority**: the findings above show gaps (no DMARC, SPF without SES) that hurt
inbox placement and reputation (principle I).

**Independent Test**: run the preflight against simulated DNS answers with and without a
DMARC record and check the result.

**Acceptance Scenarios**:

1. **Given** no DMARC record for the sender domain, **When** a production send starts without
   the force option, **Then** it refuses to run and explains what to publish; preview and test
   modes still work.
2. **Given** no DMARC record and the force option, **When** a production send starts, **Then**
   it shows a warning, continues to the batch confirmation, and records the override in the
   send log.
3. **Given** DMARC is present, **When** the preflight runs, **Then** it reports SPF and DMARC
   status in the summary.

### Edge Cases

- Temporary provider failure (for example rate limit or mailbox busy): the contact is not
  marked contacted; after 3 consecutive temporary failures the run stops.
- Run started outside the send window: nothing is sent; the summary shows when the window
  opens.
- No eligible contacts: the step reports zero and exits without connecting to the provider.
- Several eligible contacts at the same company: only one is emailed in the campaign (FR-010);
  a company with a contact already emailed in the campaign gets no second email in it.
- The launch-price year has ended (after the configured date, default 2026-12-31): preview,
  test and production refuse to run until the sentence is updated (FR-005).
- That date passes while a production run is in progress: sending stops before the next email.
- A second production batch is started before the manual inbox check has been recorded since the
  previous batch: it refuses to run and says why (FR-018).
- Company name missing: the first line uses "su empresa".
- The SES account is still in the sandbox: production send fails for unverified recipients;
  the provider's rejection is reported as a temporary failure and stops the run.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The first email MUST be plain text in Spanish, with a subject and body held in a
  template the operator can edit without changing code, using placeholders for company,
  contact name, city and sender.
- **FR-002**: The system MUST refuse to render or send a template that contains a web address,
  HTML markup or an attachment (Constitution principle III).
- **FR-003**: The system MUST apply the fallbacks for a missing contact name, city or company,
  and MUST present company names in readable capitalization.
- **FR-004**: Every first email MUST end with the opt-out sentence ("responda 'no' y no le
  vuelvo a escribir").
- **FR-005**: The urgency sentence MUST state that the launch price is kept for the whole year
  with the best price–quality ratio on the market, MUST NOT state a price amount, and the
  system MUST refuse to preview, test or send after the configured end of the launch-price
  year (default 2026-12-31).
- **FR-006**: The default mode MUST be a dry run that writes a preview file and prints counts
  only, without contacting the email provider or changing the database.
- **FR-007**: Test mode MUST deliver only to operator-configured test addresses and MUST NOT
  change the database.
- **FR-008**: Production mode MUST require an explicit option plus an interactive confirmation
  showing campaign, recipient count, hourly cap and batch limit.
- **FR-009**: A contact MUST be eligible for the first email only if times contacted is 0, it
  is not bounced, responded or opted out, and it is classified personal. Contacts from the
  2020 source are ordered before 2009.
- **FR-010**: The system MUST select at most one eligible contact per company key per campaign:
  the one with the most filled fields, 2020 source before 2009, earliest source row on ties.
  Other contacts at that company are skipped in the campaign and counted in the summary.
- **FR-011**: Sending MUST respect a configurable hourly cap (default 20 per hour), a per-run
  batch limit (default 100) and a send window (default Monday–Friday, 08:00–17:00
  America/Caracas).
- **FR-012**: The system MUST record each send attempt before contacting the provider and its
  outcome after; it MUST NOT send to a contact that already has an attempt for the same
  campaign step, whatever its outcome.
- **FR-013**: On acceptance by the provider, the system MUST increase times contacted by 1 and
  set last contacted; on permanent rejection it MUST mark the contact bounced.
- **FR-014**: Before each email, the system MUST compute the campaign's bounce rate (bounced ÷
  sent, including bounces recorded after the manual inbox check) and MUST stop when it exceeds 2% after at
  least 20 sends.
- **FR-015**: Before a production send, the system MUST check the sender domain's DMARC and SPF
  records. When DMARC is missing it MUST refuse production sending unless the operator passes
  an explicit force option, in which case it MUST warn and record the override in the send
  log.
- **FR-016**: Emails MUST use the sender name and address configured in `.env`, with replies
  going to the sender's own inbox (reviewed manually by the operator).
- **FR-017**: Every run MUST print a summary of counts (eligible, previewed, sent, rejected,
  temporary failures, skipped, bounce rate) and MUST NOT print contact values.
- **FR-018**: After the first production batch, the system MUST refuse to start another
  production batch unless a manual inbox check (`runs` row of kind `inbox`) was recorded after the
  previous batch ended.

### Key Entities

- **Template**: subject and body text with placeholders, plus fallback lines.
- **Campaign**: a named send of one template step (first email) with its caps, window, batch
  limit and launch-price end date.
- **Send attempt**: one contact, campaign, time, and outcome (pending, accepted, permanent
  rejection, temporary failure, unknown).
- **Contact** (from spec 001): read for eligibility; times contacted, last contacted and
  bounced are updated.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero contacts receive the first email more than once, including after
  interrupted runs.
- **SC-002**: 100% of sent emails are plain text with no web address, HTML or attachment.
- **SC-003**: The hourly cap and batch limit are never exceeded in any run.
- **SC-004**: Sending stops before the next email once the campaign bounce rate exceeds 2%
  (after 20 sends).
- **SC-005**: Test emails land in the inbox (not spam) of at least two different test mail
  providers before the first production batch.
- **SC-006**: The first production batch of 100 ends with a bounce rate at or below 2%.
- **SC-007**: A dry run over the whole database completes in under one minute and sends
  nothing.
- **SC-008**: Zero emails are sent after the launch-price end date, and no company
  receives the first email more than once per campaign.

## Assumptions

- The sender name in `.env` is a real person at the company; the email is written in the
  formal "usted" form, which suits unknown business owners in Venezuela.
- The SES account is out of the sandbox with DKIM enabled, and `.env` holds production
  settings (confirmed by the operator, 2026-09-13).
- Publishing DMARC and adding SES to SPF (or a custom MAIL FROM domain) are DNS changes the
  operator makes manually outside this project; the preflight only checks them.
- "The best price–quality ratio on the market" is the operator's own claim about Nómina
  Atenea; the operator is responsible for it being defensible.
- Without automatic inbox processing, only rejections returned during sending count as bounces
  until the operator records others; batches after the first wait for the manual inbox check (FR-018).
- Out of scope: follow-up emails, the landing-page link email, the landing page itself, and
  reading replies or bounce notifications (done manually).
