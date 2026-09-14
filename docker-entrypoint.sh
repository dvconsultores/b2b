#!/usr/bin/env bash
#
# docker-entrypoint.sh — commands for the b2b outreach container.
#
#   send                 one production batch: 20/hour inside the send window, waits
#                        overnight/weekends, stops when the batch ends, emails the
#                        counts-only summary to TEST_RECIPIENTS. Requires
#                        CONFIRM_CAMPAIGN=<campaign name>; FORCE_NO_DMARC=1 optional.
#   preview              write the next batch to /app/data/previews (sends nothing)
#   mark-inbox-checked   record the manual inbox check (releases the batch hold)
#   <anything else>      run it as a command
set -euo pipefail

DATA_DIR="${DATA_DIR:-/app/data}"
DB="$DATA_DIR/b2b.sqlite3"
ENV_FILE="${ENV_FILE:-$DATA_DIR/.env}"

case "${1:-send}" in
    send)
        if [[ -z "${CONFIRM_CAMPAIGN:-}" ]]; then
            echo "send_first_email: error: set CONFIRM_CAMPAIGN to the campaign name to start sending" >&2
            exit 3
        fi
        args=(--mode send --db "$DB" --env "$ENV_FILE" --confirm "$CONFIRM_CAMPAIGN"
              --wait-for-window --notify)
        if [[ "${FORCE_NO_DMARC:-0}" == "1" ]]; then
            args+=(--force-no-dmarc)
        fi
        exec python -m b2b.send_first_email "${args[@]}"
        ;;
    preview)
        exec python -m b2b.send_first_email --mode preview --db "$DB" --env "$ENV_FILE" \
            --previews-dir "$DATA_DIR/previews"
        ;;
    mark-inbox-checked)
        exec python -m b2b.mark_inbox_checked --db "$DB"
        ;;
    *)
        exec "$@"
        ;;
esac
