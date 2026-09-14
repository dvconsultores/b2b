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

Never put `CONFIRM_CAMPAIGN` in `.env`; give it on the command line for each launch.

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
CONFIRM_CAMPAIGN=primer-contacto-2026 docker compose -f b2b.yml up -d
docker compose -f b2b.yml logs -f              # import summary, confirmation block, waits, final summary
```

- DMARC not published yet: put `FORCE_NO_DMARC=1` before `docker compose` (recorded in the database).
- `CONFIRM_CAMPAIGN` must equal `name` in `config/campaign.toml`, otherwise nothing is sent.
- If the import fails, the container exits and nothing is sent.
- Stop safely at any time with `docker compose -f b2b.yml stop` (the email in flight is never re-sent).
- The container exits when the batch is done and you receive the summary email.

## 4. After a batch (manual inbox check)

1. Read the sender inbox: bounces, replies, "no" / opt-out answers.
2. Update the affected contacts (until a tool exists, ask Claude to prepare the update).
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
