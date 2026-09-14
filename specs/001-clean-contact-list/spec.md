# Feature Specification: Clean Contact Database

**Feature Branch**: `001-clean-contact-list` (feature directory; the project has no git)

**Created**: 2026-09-13

**Status**: Draft — clarified, ready for planning

**Input**: User description: "docs/plan.md §6 Parts A–D — load both Excel files, clean and
normalize emails and cities, remove duplicates keeping the most complete record, and classify
addresses as personal or generic. No sending." Amended: "create a SQLite DB to store the
emails only valid to be sent, with a field to manage the contact number, if it was bounced,
if it received a response."

## Clarifications

### Session 2026-09-13

- Q: How far should addresses be verified beyond format? → A: Check that each address's
  domain exists and accepts mail (DNS lookup of the domain only; no email is sent, no mailbox
  is probed, no third-party verification service).
- Q: When a company has several distinct addresses, what does the database keep? → A: Every
  valid address; records share a company key so a campaign can choose how many people per
  company to contact (decided in spec 002).
- Q: How are the 2009 Year Book contacts handled? → A: Included with the same cleaning and
  tagged with their source year, so campaigns can start with the 2020 client list.
- Q: Where is the result stored? → A: A local SQLite database that holds only addresses valid
  to be sent. Rejected rows and anomalies stay in report files for review.
- Q: What does "a field to manage the contact number" mean? → A: How many times the address
  has been emailed, with the date of the last email — next to bounced and responded fields.

## Source Data (profiled 2026-09-13, structure and counts only)

| Source | Sheets | Columns | Data rows | Addresses |
|--------|--------|---------|-----------|-----------|
| `contactos/ClientesFebrero2020.xls` | `Clientes` (data), `SQL` (empty) | RIF, NOMBRE, DIR1, DIR2, DIR3, TLF, CIUDAD, MAIL, AREA | 1,620 | 1,600 parsable, 1,510 unique, 90 repeated, 6 unparsable, 14 rows without `@`, 485 need case/space fixes, 56 generic |
| `contactos/Year Book 2009.xlsx` | `1-100` … `13-100` (data), `14-100` (header only) | EMPRESA, CONTACTO, CORREO, CIUDAD | 1,287 | 1,286 parsable, 1,281 unique, 2 cells with two `@`, 1 unparsable, 5 generic |

- No address appears in both files; 2,791 unique addresses in total.
- CIUDAD is empty in 712 of 1,620 rows of the 2020 file.
- Two EMPRESA cells in the 2009 file contain an `@`.
- The 2020 file has no contact-person column; the 2009 file has no tax ID or area.
- Source years: 2020 for the client file, 2009 for the Year Book.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Database of addresses valid to be sent (Priority: P1)

The operator runs the cleaning step on the two source files and gets a contact database where
every contact has a valid, normalized email address whose domain accepts mail, appears once,
and states where it came from.

**Why this priority**: every later step (sending, bounce and reply processing) works from this
database. A dirty list is the main cause of bounces, which put the sending account at risk.

**Independent Test**: run the step on synthetic copies of both file layouts with known defects
(case and spaces, invalid addresses, repeats, empty sheets, domains that do not accept mail)
with domain lookups simulated, and compare the database contents with the expected contacts.

**Acceptance Scenarios**:

1. **Given** both source files, **When** the operator runs the cleaning step, **Then** the
   database holds one contact per valid address with company, company key, contact name (when
   present), email, city, tax ID and area (when present), classification, and source file,
   sheet, row and year.
2. **Given** an address with uppercase letters or surrounding/inner spaces, **When** cleaned,
   **Then** it is stored lowercase with no spaces.
3. **Given** a row whose email is empty or not a valid address, **When** cleaned, **Then** it is
   not stored and is listed in the rejects report with the reason.
4. **Given** an address whose domain does not exist or has no mail server, **When** cleaned,
   **Then** it is not stored and is listed in the rejects report with reason "domain does not
   accept mail".
5. **Given** a domain lookup that cannot complete (no network, timeout), **When** cleaned,
   **Then** the address is not stored, is listed in the review report as "unverified", and is
   checked again on the next run.
6. **Given** the same address in several rows, **When** cleaned, **Then** the database keeps one
   contact for it — built from the row with the most filled fields, earliest source row on
   ties — and the summary counts the merged rows.
7. **Given** two different addresses at the same company, **When** cleaned, **Then** both are
   stored with the same company key.
8. **Given** a sheet with no data rows, **When** cleaned, **Then** it is skipped and named in
   the summary.
9. **Given** a cell containing two addresses, **When** cleaned, **Then** each valid address
   becomes its own contact with the same company, contact name and city, and both are listed
   in the review report.
10. **Given** the source files, **When** the step finishes, **Then** the source files are
    unchanged.

---

### User Story 2 - Contact tracking fields (Priority: P1)

Each contact carries its outreach state — how many times it has been emailed and when last,
whether it bounced, whether it responded, and whether it opted out — so sending never repeats
or reaches a bad address, and replies can be recorded.

**Why this priority**: the constitution (principle II) forbids sending without a tracker
checked before every send; specs 002 and 003 read and update these fields.

**Independent Test**: build the database from synthetic inputs, change tracking fields on some
contacts, re-run the cleaning step with an extra new address, and check that the changed
fields are intact and the new contact starts clean.

**Acceptance Scenarios**:

1. **Given** a newly stored contact, **When** the operator inspects it, **Then** times contacted
   is 0, last contacted is empty, bounced is no, responded is no and opted out is no.
2. **Given** a contact that has been emailed, bounced, responded or opted out, **When** the
   cleaning step runs again, **Then** those tracking values are unchanged.
3. **Given** a re-run where a source row adds a new valid address, **When** it finishes,
   **Then** the new contact is added with starting tracking values.
4. **Given** a re-run where an existing contact's domain now fails the check, **When** it
   finishes, **Then** the contact stays in the database unchanged and is listed in the review
   report.

---

### User Story 3 - Personal vs generic classification (Priority: P1)

Each contact is marked personal (a named person's mailbox) or generic (a role mailbox such as
info@, ventas@, contacto@), so the first campaign can start with personal addresses only.

**Why this priority**: the plan's first campaign targets personal addresses; the database is
not usable for that without the split.

**Independent Test**: run the classification on a synthetic list of known personal and role
addresses and check every label.

**Acceptance Scenarios**:

1. **Given** an address whose local part is a role word from the reviewable role-word list
   (for example info, ventas, contacto, administracion, rrhh, compras, gerencia), optionally
   followed by digits, **When** classified, **Then** it is marked generic.
2. **Given** any other address (for example firstname.lastname or an initial plus surname),
   **When** classified, **Then** it is marked personal.
3. **Given** a finished run, **When** the operator reads the summary, **Then** it shows personal
   and generic counts per source file.

---

### User Story 4 - Quality report before any use of the database (Priority: P2)

The operator reads a summary and two short reports (rejects and items needing review) to
decide whether the database is ready for sending, without opening the source files.

**Why this priority**: it lets the operator catch data problems early; the database itself is
still usable without it.

**Independent Test**: run on synthetic inputs with known defects and check that every count
reconciles and every defect is listed.

**Acceptance Scenarios**:

1. **Given** a finished run, **When** the operator reads the summary, **Then** for each source
   it shows rows read, empty sheets skipped, stored, new this run, rejected by reason,
   unverified, duplicates merged, personal, generic, missing city and distinct companies — and
   the numbers reconcile to rows read.
2. **Given** anomalies (an `@` in a company cell, a split multi-address cell, a city not in
   the city mapping, an unverified domain, a stored contact whose domain now fails), **When**
   the run finishes, **Then** each is listed in the review report with its source reference.
3. **Given** a run, **When** it prints to the screen, **Then** only counts appear, never
   contact values.

### Edge Cases

- A company cell contains an address: the contact is stored using its email column, and the
  row is listed in the review report.
- City is empty: the contact is stored with an empty city and counted as missing city.
- City spelling variants (case, accents, extra spaces, known abbreviations): mapped to one
  canonical name through a reviewable mapping; values not in the mapping are kept as written
  and listed for review, never guessed.
- A repeated address with conflicting company or city: the most complete row wins; the
  conflict is counted in the summary.
- The same company written differently across rows (case, accents, punctuation, legal suffix
  such as "C.A."): the company key groups them; the tax ID groups rows of the 2020 file when
  present.
- Many addresses share a domain (for example a free-mail provider): the domain is looked up
  once per run.
- A header row missing or renamed in a source sheet: the run stops with a clear message
  naming the file and sheet, and the database is left unchanged.
- The run fails partway: the database is left as it was before the run.
- Report files already exist from a previous run: they are replaced; the source files are
  never touched.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST read every data sheet of both source files, using the column
  headers listed in Source Data, and skip sheets with no data rows.
- **FR-002**: The system MUST normalize addresses by removing all whitespace and lowercasing,
  and MUST NOT store addresses that are empty or do not have the form local-part@domain.tld.
- **FR-003**: The system MUST check that each distinct domain exists and accepts mail, and MUST
  store only addresses whose domain passed. Addresses whose check cannot complete are listed
  as unverified and retried on the next run. Only the domain name is looked up; no email is
  sent and no mailbox is probed.
- **FR-004**: The system MUST store each address once across and within both files, built from
  the row with the most filled fields (earliest source row on ties).
- **FR-005**: The system MUST store every distinct valid address at a company and MUST give
  contacts of the same company a shared company key.
- **FR-006**: The system MUST classify each contact as personal or generic using a role-word
  list that the operator can review and edit without changing code.
- **FR-007**: The system MUST normalize city names (trim, consistent capitalization, canonical
  names through a reviewable mapping) and MUST NOT invent a city that is not in the data.
- **FR-008**: The system MUST record for each contact its source file, sheet, row and source
  year (2020 for the client file, 2009 for the Year Book), applying the same cleaning to both.
- **FR-009**: The system MUST store contacts in a single local SQLite database file, and MUST
  write the rejects report (source reference and reason) and the review report as files a
  person can open in a spreadsheet program.
- **FR-010**: Each contact MUST have tracking fields: times contacted (starts at 0), last
  contacted date, bounced (yes/no, with date), responded (yes/no, with date) and opted out
  (yes/no, with date).
- **FR-011**: Re-running the step MUST add new valid addresses, MAY refresh descriptive fields
  (company, contact name, city, tax ID, area, classification) of existing contacts, and MUST
  NOT delete contacts or change their tracking fields.
- **FR-012**: A run MUST either complete all database changes or leave the database as it was.
- **FR-013**: The system MUST print a summary of counts that reconciles to the rows read, and
  MUST NOT print contact values.
- **FR-014**: The system MUST store only company, company key, contact name, email, city, tax
  ID, area, classification, source reference, source year and the tracking fields; postal
  addresses and phone numbers are not copied.
- **FR-015**: The system MUST NOT modify the source files or send any email, and MUST NOT
  transmit contact data outside the machine other than domain names for the FR-003 lookup.

### Key Entities

- **Source row**: one data row from a sheet; identified by file, sheet and row number.
- **Contact**: one unique normalized address valid to be sent, with company, company key,
  contact name, city, tax ID, area, classification (personal or generic), source reference,
  source year, and tracking fields (times contacted, last contacted, bounced, responded,
  opted out, each with its date).
- **Company**: the grouping of contacts that share a company key.
- **Rejected row**: a source row not stored, with its source reference and reason.
- **Review item**: an anomaly the operator should check, with its source reference and type.
- **Run summary**: per-source counts of read, skipped, stored, new, rejected by reason,
  unverified, merged, personal, generic, missing-city rows and distinct companies.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of source data rows are accounted for: rows read = contacts stored or
  already present + duplicates merged + rows rejected + unverified (+ extra contacts from
  split cells), per source.
- **SC-002**: The database contains zero repeated addresses, zero addresses that fail format
  validation, and zero addresses whose domain was found not to accept mail when stored.
- **SC-003**: In a manual check of 50 randomly chosen contacts, at least 95% are correctly
  labeled personal or generic.
- **SC-004**: Running the step twice on the same inputs, with the same domain lookup results,
  leaves the database with identical contents.
- **SC-005**: After a re-run, 100% of tracking values set before the run are unchanged.
- **SC-006**: A full run over both files (about 2,900 rows) completes in under five minutes,
  including domain lookups.
- **SC-007**: During a run, no email is sent and nothing leaves the machine except domain-name
  lookups.

## Assumptions

- The two source files are the only inputs for this feature and keep their current column
  headers.
- SQLite is a user requirement for storage and fits Constitution principle VI (local files).
- The database and reports contain real personal data; they stay on this machine and follow
  Constitution principle IV. Domain-name lookups through the machine's normal DNS resolver
  are the one approved exception (service: DNS; purpose: address verification, FR-003).
- A domain that accepts mail does not guarantee the mailbox exists; mailbox-level bounces are
  recorded after each batch through the manual inbox check (spec 003 deferred).
- NOMBRE (2020 file) and EMPRESA (2009 file) both mean company name; CONTACTO is the person's
  name; RIF is the company tax ID; AREA is kept as written.
- Contacts without a city stay in the database; the first email handles a missing city
  (spec 002).
- This feature creates the tracking fields but never changes them; spec 002 (sending) and
  the manual inbox check (bounces, opt-outs, replies) updates them, and spec 002 adds the per-send log.
- Out of scope: email templates, choosing contacts per company for a campaign, dry run,
  sending, and inbox processing.
