#!/usr/bin/env bash
#
# docker-entrypoint.sh — commands for the b2b outreach container.
#
#   send                 import contactos/ into the database (IMPORT_ON_START=1), then one
#                        production batch: 20/hour inside the send window, waits
#                        overnight/weekends, stops when the batch ends, emails the
#                        counts-only summary to TEST_RECIPIENTS. Requires
#                        CONFIRM_CAMPAIGN=<campaign name>; FORCE_NO_DMARC=1 optional.
#   preview              import (as above), then write the next batch to data/previews (sends nothing)
#   import               only import contactos/ into the database (creates it on first run)
#   mark-inbox-checked   record the manual inbox check (releases the batch hold)
#   sync-bounces [--dry-run]  mark SES-suppressed addresses bounced / opted out in the database
#   export-verification  write data/verification/verify-emails-<time>.csv (emails only) for the verification service
#   import-verification <file> [--dry-run] [--status-column NAME]
#                        read the service's results CSV from data/verification/ into the database
#
# send always runs with --ses-guard: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION
# (read-only SES key) must be in .env.
#   <anything else>      run it as a command
#
# The import is safe to repeat: it adds new valid contacts and refreshes descriptive fields,
# and never deletes contacts or changes times contacted / bounced / responded / opted out.
set -euo pipefail

DATA_DIR="${DATA_DIR:-/app/data}"
DB="$DATA_DIR/b2b.sqlite3"
ENV_FILE="${ENV_FILE:-$DATA_DIR/.env}"
CONTACTOS_DIR="${CONTACTOS_DIR:-/app/contactos}"
CLIENTS_FILE="${CLIENTS_FILE:-ClientesFebrero2020.xls}"
YEARBOOK_FILE="${YEARBOOK_FILE:-Year Book 2009.xlsx}"
IMPORT_ON_START="${IMPORT_ON_START:-1}"

run_import() {
    local clients="$CONTACTOS_DIR/$CLIENTS_FILE"
    local yearbook="$CONTACTOS_DIR/$YEARBOOK_FILE"
    if [[ -f "$clients" && -f "$yearbook" ]]; then
        echo "import_contacts: importing contact files into $DB"
        local rc=0
        python -m b2b.import_contacts --clients "$clients" --yearbook "$yearbook" \
            --db "$DB" --reports-dir "$DATA_DIR/reports" --config-dir /app/config || rc=$?
        if [[ "$rc" -ne 0 ]]; then
            echo "import_contacts: error: import failed (exit $rc); nothing will be sent" >&2
            exit "$rc"
        fi
    elif [[ -f "$DB" ]]; then
        echo "import_contacts: contact files not found in $CONTACTOS_DIR — using the existing database"
    else
        echo "import_contacts: error: no database at $DB and no contact files in $CONTACTOS_DIR" \
             "($CLIENTS_FILE, $YEARBOOK_FILE)" >&2
        exit 1
    fi
}

maybe_import() {
    if [[ "$IMPORT_ON_START" == "1" ]]; then
        run_import
    else
        echo "import_contacts: skipped (IMPORT_ON_START=$IMPORT_ON_START)"
    fi
}

case "${1:-send}" in
    send)
        if [[ -z "${CONFIRM_CAMPAIGN:-}" ]]; then
            echo "send_first_email: error: set CONFIRM_CAMPAIGN to the campaign name to start sending" >&2
            exit 3
        fi
        maybe_import
        args=(--mode send --db "$DB" --env "$ENV_FILE" --confirm "$CONFIRM_CAMPAIGN"
              --wait-for-window --notify --ses-guard)
        if [[ "${FORCE_NO_DMARC:-0}" == "1" ]]; then
            args+=(--force-no-dmarc)
        fi
        exec python -m b2b.send_first_email "${args[@]}"
        ;;
    preview)
        maybe_import
        exec python -m b2b.send_first_email --mode preview --db "$DB" --env "$ENV_FILE" \
            --previews-dir "$DATA_DIR/previews"
        ;;
    import)
        run_import
        ;;
    mark-inbox-checked)
        exec python -m b2b.mark_inbox_checked --db "$DB"
        ;;
    sync-bounces)
        exec python -m b2b.sync_bounces --db "$DB" --env "$ENV_FILE" "${@:2}"
        ;;
    export-verification)
        exec python -m b2b.export_verification --db "$DB" --out-dir "$DATA_DIR/verification"
        ;;
    import-verification)
        results="${2:-}"
        if [[ -z "$results" ]]; then
            echo "import_verification: error: give the results file name (in data/verification/)" >&2
            exit 1
        fi
        [[ "$results" == /* ]] || results="$DATA_DIR/verification/$results"
        exec python -m b2b.import_verification "$results" --db "$DB" "${@:3}"
        ;;
    *)
        exec "$@"
        ;;
esac
