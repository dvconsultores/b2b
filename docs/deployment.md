# Deployment — unattended batches on the server

The first email is sent by a Docker container on the server. Each launch sends **one batch**
(`batch_limit`, default 100) at `hourly_cap` (default 20/hour) inside the send window
(Monday–Friday 08:00–17:00 America/Caracas), waits through nights and weekends, stops when the
batch ends, and emails a counts-only summary to `TEST_RECIPIENTS`. It never sends a second batch
on its own: the next launch is refused until you record a manual inbox check.

Nothing personal is in the image or the repository: the database and `.env` live only on this
machine and in `/opt/b2b` on the server.

## `.env` keys

| Key | Used by |
|-----|---------|
| `HOST_EMAIL`, `PORT_EMAIL`, `USER_EMAIL`, `PASS_EMAIL`, `SENDER_EMAIL`, `SMTP_FROM_NAME` | sending (SES SMTP) |
| `TEST_RECIPIENTS` | test mode and the end-of-batch summary email |
| `DOCKER_USERNAME`, `DOCKER_PASSWORD` | `deploy.sh` (Docker Hub) and the image name in `docker-compose.yml` |
| `SRVUSER`, `SRVPASS`, `SRVHOST` | `push-db.sh` (server login) |
| `SRVDB_LOCATION` (default `/opt/b2b`), `LOCADB_LOCATION` (default `data`), `DBNAME` (default `b2b.sqlite3`) | `push-db.sh` paths |

Never put `CONFIRM_CAMPAIGN` in `.env`; give it on the command line for each launch.

## 1. Publish the image (this machine)

```bash
./deploy.sh
```

Runs the tests, builds `<DOCKER_USERNAME>/b2b-outreach:latest`, checks the image holds no
`.env`, database or `contactos/`, and pushes it. The server container is excluded from
Watchtower on purpose (an automatic restart would interrupt a batch).

## 2. First-time server setup

```bash
./push-db.sh                                   # uploads data/b2b.sqlite3 → /opt/b2b/b2b.sqlite3
scp .env docker-compose.yml <SRVUSER>@<SRVHOST>:/opt/b2b/
ssh <SRVUSER>@<SRVHOST> 'chmod 600 /opt/b2b/.env'
```

`push-db.sh` asks you to type `OVERWRITE`, refuses while the container is running, refuses when
the server holds more send history than your local copy, and snapshots the server database first.
After the first batch, the **server** database is the source of truth — do not push an older local
copy over it.

## 3. Launch a batch (server)

```bash
cd /opt/b2b
docker compose pull
CONFIRM_CAMPAIGN=primer-contacto-2026 docker compose up -d
docker compose logs -f                         # confirmation block, waits, final summary
```

- DMARC not published yet: add `FORCE_NO_DMARC=1` before `docker compose up -d` (recorded in the
  database).
- `CONFIRM_CAMPAIGN` must equal `name` in `config/campaign.toml`, otherwise nothing is sent.
- Stop safely at any time with `docker compose stop` (the email in flight is never re-sent).
- The container exits when the batch is done; you receive the summary email.

## 4. After a batch (manual inbox check)

1. Read the sender inbox: bounces, replies, "no" / opt-out answers.
2. Update the affected contacts (until a tool exists, ask Claude to prepare the update).
3. Record the check, which releases the batch hold:

   ```bash
   cd /opt/b2b && docker compose run --rm b2b-outreach mark-inbox-checked
   ```

4. Launch the next batch (step 3).

## Other commands

```bash
docker compose run --rm b2b-outreach preview   # writes /opt/b2b/previews/… , sends nothing
```

From this machine: `.venv/bin/python -m b2b.send_first_email --mode test` sends synthetic samples
to `TEST_RECIPIENTS`.
