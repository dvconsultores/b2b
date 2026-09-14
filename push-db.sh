#!/usr/bin/env bash
#
# push-db.sh — Upload the b2b contact database from this machine to the server.
#
#   Local DB  : ${LOCADB_LOCATION:-data}/${DBNAME:-b2b.sqlite3}
#   Server DB : ${SRVUSER}@${SRVHOST}:${SRVDB_LOCATION:-/opt/b2b}/${DBNAME:-b2b.sqlite3}
#
# Reads SRVUSER / SRVPASS / SRVHOST / SRVDB_LOCATION / LOCADB_LOCATION / DBNAME from .env.
# Uses sshpass (password passed through the environment, never on the command line) when
# available; otherwise falls back to plain ssh/scp (SSH keys or prompt).
#
# NOTE: the local DB file is gitignored (data/ in .gitignore).
#
# ⚠️  The server DB is the SEND TRACKER (send_attempts, times_contacted, bounced, responded,
#     opted_out). Replacing it with an older copy can make the next batch email people twice.
#     This script refuses when the server holds more tracking history than your local copy,
#     refuses while the b2b-outreach container is running, and always snapshots the server DB
#     first.
#
# Re-exec under bash if invoked via `sh` (script uses bash-isms: [[ ]], ${var:-}).
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

echo "⚠️  You are about to REPLACE the server database with your local copy."
echo "    If the server has sent emails your local copy doesn't know about, contacts could be emailed twice."
read -r -p "    Type OVERWRITE to continue: " _confirm
[[ "$_confirm" == "OVERWRITE" ]] || { echo "aborted."; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

# ── Load config from .env ─────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    echo "❌ .env not found at $ENV_FILE" >&2
    exit 1
fi

env_val() {
    local key="$1" line
    line="$(grep -E "^${key}=" "$ENV_FILE" | head -1 || true)"
    [[ -z "$line" ]] && { echo ""; return; }
    echo "$line" | cut -d= -f2- \
        | sed -e 's/[[:space:]]*#.*$//' \
              -e 's/^[[:space:]]*//' \
              -e 's/[[:space:]]*$//' \
              -e 's/^"//' \
              -e 's/"$//'
}

SRVUSER="$(env_val SRVUSER)"
SRVPASS="$(env_val SRVPASS)"
SRVHOST="$(env_val SRVHOST)"
SRVDB_LOCATION="$(env_val SRVDB_LOCATION)"
LOCADB_LOCATION="$(env_val LOCADB_LOCATION)"
DBNAME="$(env_val DBNAME)"

if [[ -z "$SRVUSER" || -z "$SRVHOST" ]]; then
    echo "❌ SRVUSER / SRVHOST missing in $ENV_FILE (SRVPASS too, unless you use SSH keys)" >&2
    exit 1
fi

LOCAL_DIR="${LOCADB_LOCATION:-$SCRIPT_DIR/data}"
SERVER_DB_DIR="${SRVDB_LOCATION:-/opt/b2b}"
DB_FILE="${DBNAME:-b2b.sqlite3}"
LOCAL_DIR="${LOCAL_DIR%/}"
SERVER_DB_DIR="${SERVER_DB_DIR%/}"
case "$LOCAL_DIR" in
  /*) ;;
  *) LOCAL_DIR="$SCRIPT_DIR/${LOCAL_DIR}";;
esac
LOCAL_DB="${LOCAL_DIR}/${DB_FILE}"
REMOTE_DB="${SERVER_DB_DIR}/${DB_FILE}"

if [[ ! -f "$LOCAL_DB" ]]; then
    echo "❌ Local DB not found: $LOCAL_DB" >&2
    exit 1
fi

# ── ssh / scp helpers (password via SSHPASS env when sshpass exists) ──────
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
remote() {
    if [[ -n "$SRVPASS" ]] && command -v sshpass >/dev/null 2>&1; then
        SSHPASS="$SRVPASS" sshpass -e ssh "${SSH_OPTS[@]}" "${SRVUSER}@${SRVHOST}" "$@"
    else
        ssh "${SSH_OPTS[@]}" "${SRVUSER}@${SRVHOST}" "$@"
    fi
}
push() {
    local local_file="$1" remote_file="$2"
    if [[ -n "$SRVPASS" ]] && command -v sshpass >/dev/null 2>&1; then
        SSHPASS="$SRVPASS" sshpass -e scp "${SSH_OPTS[@]}" "$local_file" "${SRVUSER}@${SRVHOST}:$remote_file"
    else
        [[ -n "$SRVPASS" ]] && echo "⚠️  sshpass not installed — falling back to plain scp (SSH keys or prompt)." >&2
        scp "${SSH_OPTS[@]}" "$local_file" "${SRVUSER}@${SRVHOST}:$remote_file"
    fi
}

echo "🔌 Connecting to ${SRVUSER}@${SRVHOST} ..."

# ── Guard 1: never push while a batch is running ──────────────────────────
if remote "docker ps -q -f name=^b2b-outreach\$ 2>/dev/null" | grep -q .; then
    echo "❌ The b2b-outreach container is running on the server. Wait for the batch to finish (or stop it) first." >&2
    exit 1
fi

# ── Guard 2: never replace more tracking history with less ────────────────
# Tracking history = send attempts + contacts with any tracking flag set.
_tracking_py='import sqlite3,sys
c=sqlite3.connect(sys.argv[1])
def q(s):
    try: return c.execute(s).fetchone()[0] or 0
    except sqlite3.Error: return 0
print(q("SELECT COUNT(*) FROM send_attempts")+q("SELECT COUNT(*) FROM contacts WHERE times_contacted>0 OR bounced=1 OR responded=1 OR opted_out=1"))'
_local_n="$(python3 -c "$_tracking_py" "$LOCAL_DB")"
_remote_n="$(remote "if [ ! -f '$REMOTE_DB' ]; then echo none; elif command -v python3 >/dev/null 2>&1; then python3 -c '$(printf "%s" "$_tracking_py" | sed "s/'/'\\\\''/g")' '$REMOTE_DB'; else echo unknown; fi" 2>/dev/null || echo unknown)"
echo "📊 tracking history — local: ${_local_n}  server: ${_remote_n}"
if [[ "${FORCE_DB_PUSH:-0}" != "1" ]]; then
    if [[ "$_remote_n" == "unknown" ]]; then
        echo "❌ Cannot read the server DB history (no python3 on the server?). Override: FORCE_DB_PUSH=1 ./push-db.sh" >&2
        exit 1
    fi
    if [[ "$_remote_n" != "none" && "$_local_n" -lt "$_remote_n" ]]; then
        echo "❌ Refusing: the server has more send/tracking history than your local DB." >&2
        echo "   Pushing could email contacts twice. Pull the server DB first, or override: FORCE_DB_PUSH=1 ./push-db.sh" >&2
        exit 1
    fi
fi

# ── Snapshot the server DB, then upload ───────────────────────────────────
remote "mkdir -p '$SERVER_DB_DIR'"
if [[ "$_remote_n" != "none" ]]; then
    _stamp="$(date +%Y%m%d-%H%M%S)"
    remote "cp -p '$REMOTE_DB' '$REMOTE_DB.bak-$_stamp'"
    echo "🗄️  server snapshot: $REMOTE_DB.bak-$_stamp"
fi

echo "📤 Uploading $LOCAL_DB → $REMOTE_DB"
echo "⚠️  This OVERWRITES the server database. Ctrl+C within 3s to abort..."
sleep 3

push "$LOCAL_DB" "$REMOTE_DB"

for ext in -wal -journal -shm; do
    if [[ -f "${LOCAL_DB}${ext}" ]]; then
        if push "${LOCAL_DB}${ext}" "${REMOTE_DB}${ext}"; then
            echo "   ✓ uploaded ${DB_FILE}${ext}"
        fi
    fi
done

echo "✅ Success. Database uploaded to: ${SRVUSER}@${SRVHOST}:${REMOTE_DB}"
