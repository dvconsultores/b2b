# Deployment — unattended batches on the server

The first email is sent by a Docker container on the server. On every start it first **imports
the contact spreadsheets** into the database (creating the database and tables the first time),
then sends **one batch** (`batch_limit`, default 100) at `hourly_cap` (default 20/hour) inside the
send window (Monday–Friday 08:00–17:00 America/Caracas), waits through nights and weekends, stops
when the batch ends, and emails a counts-only summary to `TEST_RECIPIENTS`. It never sends a second
batch on its own: the next launch is refused until you record a manual inbox check.

The import is safe to repeat: it adds new valid contacts and refreshes descriptive fields, and never
deletes contacts or changes times contacted, bounced, responded or opted out.

Nothing personal is in the image or the repository: the spreadsheets, the database and `.env` live
only on this machine and in `/opt/b2b` on the server.

## Server layout

```text
/opt/b2b/
├── b2b.yml              # compose file (from this repository)
├── .env                 # same keys as locally; chmod 600
├── contactos/           # ClientesFebrero2020.xls, Year Book 2009.xlsx (push-contactos.sh); read-only mount
└── data/
    ├── b2b.sqlite3      # created by the import on first start — the send tracker
    └── reports/         # rejects.csv, review.csv from each import
```

## `.env` keys

See `.env.example` for the full list.

| Key | Used by |
|-----|---------|
| `HOST_EMAIL`, `PORT_EMAIL`, `USER_EMAIL`, `PASS_EMAIL`, `SENDER_EMAIL`, `SMTP_FROM_NAME` | sending (SES SMTP) |
| `TEST_RECIPIENTS` | test mode and the end-of-batch summary email |
| `DOCKER_USERNAME`, `DOCKER_PASSWORD` | `deploy.sh` (Docker Hub) and the image name in `b2b.yml` |
| `SRVUSER`, `SRVPASS`, `SRVHOST` | `push-contactos.sh`, `push-db.sh` (server login) |
| `SRVCONTACTOS_LOCATION` (default `/opt/b2b/contactos`) | `push-contactos.sh` target |
| `SRVDB_LOCATION` (default `/opt/b2b/data`), `LOCADB_LOCATION` (default `data`), `DBNAME` (default `b2b.sqlite3`) | `push-db.sh` paths |
| `IMPORT_ON_START` (default `1`), `CLIENTS_FILE`, `YEARBOOK_FILE` | container start: import before sending |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | read-only SES key: bounce sync and the send guard (**required** for `send`) |

Never put `CONFIRM_CAMPAIGN` in `.env`; give it on the command line for each launch.

## Bounce guard (SES API)

SES accepts every email at SMTP time and reports bounces later, so `send` always runs with the
SES guard (spec 003): before starting and before every email it copies the SES suppression list
into the database (bounces → bounced, complaints → opted out) and checks the real bounce rate.

- More than 2% bounces in the last 24 hours (at least 20 sends) → the run does not start (exit 3).
- More than 2% since the run started → it stops before the next email (`ses_bounce_rate`).
- SES API unreachable → it stops instead of sending blind (`ses_check_failed`).
- The campaign's own 2% rule also sees the synced bounces, so a campaign that bounced badly stays
  paused until you decide what to do with the list.

## Email verification (before every new campaign)

The first campaign bounced at 18%: the domain check cannot tell whether a mailbox still exists.
Campaigns now send only to addresses a verification service confirmed (`allowed_verification`
in `config/campaign.toml`, default `["valid"]`). Only the email addresses leave the server
(spec 004, constitution 1.3.0).

```bash
# 1. server: export the addresses that still need verifying (emails only)
cd /opt/b2b && docker compose -f b2b.yml run --rm b2b-outreach export-verification
#    → data/verification/verify-emails-<time>.csv  (count printed)

# 2. this machine: download it, upload to NeverBounce or ZeroBounce (web), download the results CSV
scp <SRVUSER>@<SRVHOST>:/opt/b2b/data/verification/verify-emails-<time>.csv ~/
scp ~/results.csv <SRVUSER>@<SRVHOST>:/opt/b2b/data/verification/results.csv
rm ~/verify-emails-<time>.csv ~/results.csv          # do not keep copies around

# 3. server: import (dry run first)
docker compose -f b2b.yml run --rm b2b-outreach import-verification results.csv --dry-run
docker compose -f b2b.yml run --rm b2b-outreach import-verification results.csv
```

If the results file uses other column names, add `--email-column NAME --status-column NAME`.
After importing, run `preview` and check `eligible contacts` and `skipped not verified`.
A company that already received the first email is never emailed again, in any campaign.

## 1. Publish the image (this machine)

```bash
./deploy.sh
```

Runs the tests, builds `<DOCKER_USERNAME>/b2b-outreach:latest`, checks the image holds no `.env`,
database or `contactos/`, and pushes it. The container is excluded from Watchtower on purpose (an
automatic restart would interrupt a batch), so the server only changes image when you pull.

## 2. First-time server setup

```bash
ssh <SRVUSER>@<SRVHOST> 'mkdir -p /opt/b2b/data'
./push-contactos.sh                              # contactos/*.xls[x] → /opt/b2b/contactos/
scp .env b2b.yml <SRVUSER>@<SRVHOST>:/opt/b2b/
ssh <SRVUSER>@<SRVHOST> 'chmod 600 /opt/b2b/.env'
```

The database does not need to be uploaded: the container creates it from the spreadsheets. To reuse
the database from this machine instead, run `./push-db.sh` (it asks for `OVERWRITE`, refuses while
the container runs or when the server has more send history, and snapshots the server copy first).
After the first batch, the **server** database is the source of truth.

Optional check before the first batch (imports and writes a preview, sends nothing):

```bash
cd /opt/b2b && docker compose -f b2b.yml run --rm b2b-outreach preview
```

## 3. Launch a batch (server)

```bash
cd /opt/b2b
docker compose -f b2b.yml pull
CONFIRM_CAMPAIGN=primer-contacto-2026-b docker compose -f b2b.yml up -d
docker compose -f b2b.yml logs -f              # import summary, confirmation block, waits, final summary
```

- DMARC not published yet: put `FORCE_NO_DMARC=1` before `docker compose` (recorded in the database).
- `CONFIRM_CAMPAIGN` must equal `name` in `config/campaign.toml`, otherwise nothing is sent.
- If the import fails, the container exits and nothing is sent.
- Stop safely at any time with `docker compose -f b2b.yml stop` (the email in flight is never re-sent).
- The container exits when the batch is done and you receive the summary email.

## 4. After a batch (manual inbox check)

1. Sync bounces and complaints from SES (also done automatically by every `send`):

   ```bash
   cd /opt/b2b && docker compose -f b2b.yml run --rm b2b-outreach sync-bounces   # add --dry-run to only count
   ```

2. Read the sender inbox for replies and "no" / opt-out answers, and ask Claude to prepare the
   update for those contacts.
3. Record the check, which releases the batch hold:

   ```bash
   cd /opt/b2b && docker compose -f b2b.yml run --rm b2b-outreach mark-inbox-checked
   ```

4. Launch the next batch (step 3).

## Other commands

```bash
docker compose -f b2b.yml run --rm b2b-outreach import    # only import the spreadsheets
docker compose -f b2b.yml run --rm b2b-outreach preview   # import, then write data/previews/…, sends nothing
```

Set `IMPORT_ON_START=0` in `.env` to skip the import on start. From this machine:
`.venv/bin/python -m b2b.send_first_email --mode test` sends synthetic samples to `TEST_RECIPIENTS`.
