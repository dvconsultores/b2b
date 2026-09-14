#!/usr/bin/env bash
#
# deploy.sh — test, build & publish the b2b outreach Docker image to Docker Hub from THIS machine.
#
#   ./deploy.sh            # run tests, build + push <DOCKER_USERNAME>/b2b-outreach:latest
#
# Everything runs against the local Docker engine on this machine. The image holds code and
# config only — never .env, contactos/ or data/ (see .dockerignore). The server container is
# excluded from Watchtower on purpose (a restart would interrupt a batch), so after pushing,
# update it between batches with:  cd /opt/b2b && docker compose pull
#
# Docker Hub login uses DOCKER_USERNAME / DOCKER_PASSWORD from .env (password via
# stdin — it never appears on a command line).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
[[ -f "$ENV_FILE" ]] || { echo "❌ .env not found" >&2; exit 1; }

env_val() {
    local line
    line="$(grep -E "^$1=" "$ENV_FILE" | head -1 || true)"
    [[ -z "$line" ]] && { echo ""; return; }
    echo "$line" | cut -d= -f2- | sed -e 's/[[:space:]]*#.*$//' -e 's/^[[:space:]]*//' \
        -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//'
}

HUB_USER="$(env_val DOCKER_USERNAME)"; HUB_USER="${HUB_USER:-andresdom2004}"
HUB_PASS="$(env_val DOCKER_PASSWORD)"
IMAGE="$HUB_USER/b2b-outreach"

# ── Docker daemon availability ────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ docker is not installed." >&2
    echo "   Install once:  sudo apt install docker.io" >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "❌ cannot reach the local Docker daemon." >&2
    echo "   Fix access with:" >&2
    echo "     sudo systemctl start docker      # start the daemon" >&2
    echo "     sudo usermod -aG docker \$USER    # grant your user access" >&2
    echo "     newgrp docker                     # apply the group in this shell" >&2
    echo "   Then re-run $0." >&2
    exit 1
fi

# ── Tests (synthetic data, no network) ────────────────────────────────────────
if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    echo "🧪 running tests"
    (cd "$SCRIPT_DIR" && .venv/bin/python -m pytest -q) || { echo "❌ tests failed — not deploying" >&2; exit 3; }
else
    echo "⚠️  .venv not found — skipping tests." >&2
fi

# ── Commit ────────────────────────────────────────────────────────────────────
COMMIT="$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
if [[ -n "$(git -C "$SCRIPT_DIR" status --porcelain 2>/dev/null)" ]]; then
    echo "⚠️  uncommitted changes exist and WILL be included (local build uses the working tree)." >&2
fi

# ── Docker Hub login ──────────────────────────────────────────────────────────
if [[ -n "$HUB_PASS" ]]; then
    printf '%s' "$HUB_PASS" | docker login -u "$HUB_USER" --password-stdin >/dev/null 2>&1 \
        || { echo "❌ docker hub login failed for $HUB_USER" >&2; exit 2; }
    echo "🔐 docker hub login ok ($HUB_USER)"
else
    docker login >/dev/null 2>&1 \
        || { echo "❌ not logged in to Docker Hub. Add DOCKER_USERNAME/DOCKER_PASSWORD to .env, or run  docker login ." >&2; exit 2; }
fi

# ── Build + push ──────────────────────────────────────────────────────────────
echo "🐳 building $IMAGE:latest (commit $COMMIT)"
docker build --label "org.opencontainers.image.revision=$COMMIT" -t "$IMAGE:latest" -t "$IMAGE:$COMMIT" "$SCRIPT_DIR"

# Last guard: the image must not contain secrets or contact data.
if docker run --rm --entrypoint sh "$IMAGE:latest" -c 'ls -A /app; test ! -e /app/.env && test ! -e /app/data/b2b.sqlite3 && test ! -e /app/contactos' >/dev/null; then
    echo "🔎 image check ok (no .env, database or contactos inside)"
else
    echo "❌ image contains .env, a database or contactos — not pushing" >&2
    exit 4
fi

docker push "$IMAGE:latest"
[[ "$COMMIT" != "unknown" ]] && docker push "$IMAGE:$COMMIT"

echo "✅ pushed $IMAGE:latest — on the server, between batches:  cd /opt/b2b && docker compose pull"
