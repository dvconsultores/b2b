#!/usr/bin/env bash
#
# push-contactos.sh — Upload the contact spreadsheets from this machine to the server.
#
#   Local  : contactos/${CLIENTS_FILE} and contactos/${YEARBOOK_FILE}
#   Server : ${SRVUSER}@${SRVHOST}:${SRVCONTACTOS_LOCATION:-/opt/b2b/contactos}/
#
# The b2b-outreach container mounts that folder read-only and imports it into the database on
# every start (IMPORT_ON_START=1). Re-importing is safe: tracking fields are never reset.
#
# Reads SRVUSER / SRVPASS / SRVHOST / SRVCONTACTOS_LOCATION / CLIENTS_FILE / YEARBOOK_FILE from
# .env. Uses sshpass (password through the environment, never on the command line) when
# available; otherwise plain ssh/scp (SSH keys or prompt).
#
# ⚠️  These files are real personal data: they are never committed or built into images.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
[[ -f "$ENV_FILE" ]] || { echo "❌ .env not found at $ENV_FILE" >&2; exit 1; }

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
REMOTE_DIR="$(env_val SRVCONTACTOS_LOCATION)"; REMOTE_DIR="${REMOTE_DIR:-/opt/b2b/contactos}"
CLIENTS_FILE="$(env_val CLIENTS_FILE)"; CLIENTS_FILE="${CLIENTS_FILE:-ClientesFebrero2020.xls}"
YEARBOOK_FILE="$(env_val YEARBOOK_FILE)"; YEARBOOK_FILE="${YEARBOOK_FILE:-Year Book 2009.xlsx}"
REMOTE_DIR="${REMOTE_DIR%/}"

if [[ -z "$SRVUSER" || -z "$SRVHOST" ]]; then
    echo "❌ SRVUSER / SRVHOST missing in $ENV_FILE (SRVPASS too, unless you use SSH keys)" >&2
    exit 1
fi

for file in "$CLIENTS_FILE" "$YEARBOOK_FILE"; do
    [[ -f "$SCRIPT_DIR/contactos/$file" ]] || { echo "❌ Local file not found: contactos/$file" >&2; exit 1; }
done

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
        scp "${SSH_OPTS[@]}" "$local_file" "${SRVUSER}@${SRVHOST}:$remote_file"
    fi
}

echo "🔌 Connecting to ${SRVUSER}@${SRVHOST} ..."
remote "mkdir -p '$REMOTE_DIR' && chmod 700 '$REMOTE_DIR'"

for file in "$CLIENTS_FILE" "$YEARBOOK_FILE"; do
    echo "📤 Uploading contactos/$file → $REMOTE_DIR/"
    push "$SCRIPT_DIR/contactos/$file" "$REMOTE_DIR/$file"
done
remote "chmod 600 '$REMOTE_DIR'/*"

echo "✅ Contact files uploaded to ${SRVUSER}@${SRVHOST}:${REMOTE_DIR}/ — imported on the next container start."
