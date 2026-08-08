#!/usr/bin/env bash
#
# RagReader deploy script.
#
# Runs the automated test gate first, and only builds/starts the stack when
# every test passes:
#
#   1. Build the backend image
#   2. Run the Django test suite inside that image (no Redis/Postgres/API
#      keys needed — tests are hermetic)
#   3. Build the frontend image (its Dockerfile runs `tsc -b && vite build`,
#      which is the frontend type-check gate)
#   4. docker compose up -d
#   5. Wait for the backend to answer over HTTP
#
# Usage:
#   ./deploy.sh              # test gate + build + deploy
#   ./deploy.sh test         # run the test gate only, do not deploy
#   ./deploy.sh --skip-tests # emergency deploy without the test gate
#
set -euo pipefail

cd "$(dirname "$0")"

BOLD=$(tput bold 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)

log()  { echo "${BOLD}[deploy]${RESET} $*"; }
fail() { echo "${BOLD}[deploy] ERROR:${RESET} $*" >&2; exit 1; }

MODE="full"
case "${1:-}" in
    test)         MODE="test-only" ;;
    --skip-tests) MODE="skip-tests" ;;
    "")           ;;
    *)            fail "unknown argument: $1 (expected 'test' or '--skip-tests')" ;;
esac

# ── Preflight ────────────────────────────────────────────────────────────────

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
docker info >/dev/null 2>&1 || fail "docker daemon is not running"

if [ "$MODE" != "test-only" ]; then
    [ -f backend/.env ]  || fail "backend/.env is missing  (cp .env.example backend/.env and fill it in)"
    [ -f frontend/.env ] || fail "frontend/.env is missing (cp frontend/.env.example frontend/.env)"
fi

# ── 1. Build backend image ───────────────────────────────────────────────────

log "Building backend image..."
docker compose build backend

# ── 2. Backend test gate ─────────────────────────────────────────────────────

if [ "$MODE" != "skip-tests" ]; then
    log "Running backend test suite..."
    # --no-deps / --entrypoint "": no Redis/Postgres, no migrate/collectstatic.
    # DEVELOPMENT_MODE=True    -> tests run against sqlite inside the container
    # RAG_DISABLE_ENGINE_INIT  -> no model downloads / API keys needed
    docker compose run --rm --no-deps --entrypoint "" \
        -e DEVELOPMENT_MODE=True \
        -e DEBUG=False \
        -e RAG_DISABLE_ENGINE_INIT=1 \
        -e DATABASE_URL= \
        backend \
        python manage.py test --noinput -v 2 \
        || fail "backend tests failed — deploy aborted"
    log "Backend tests passed."
else
    log "Skipping tests (--skip-tests)."
fi

if [ "$MODE" = "test-only" ]; then
    log "Test gate finished. Skipping deploy (test-only mode)."
    exit 0
fi

# ── 3. Build frontend image (includes tsc type-check) ───────────────────────

log "Building frontend image (runs tsc + vite build)..."
docker compose build frontend || fail "frontend build failed — deploy aborted"

# ── 4. Start the stack ───────────────────────────────────────────────────────

log "Starting services..."
docker compose up -d --remove-orphans

# ── 5. Health check ──────────────────────────────────────────────────────────

BACKEND_PORT="${BACKEND_PORT:-8050}"
FRONTEND_PORT="${FRONTEND_PORT:-5150}"
HEALTH_URL="http://localhost:${BACKEND_PORT}/api/schema/"

log "Waiting for backend at ${HEALTH_URL} ..."
for i in $(seq 1 30); do
    if curl -fsS -o /dev/null "$HEALTH_URL"; then
        log "Backend is up."
        log "Deploy complete: frontend http://localhost:${FRONTEND_PORT}  backend http://localhost:${BACKEND_PORT}"
        exit 0
    fi
    sleep 2
done

echo
docker compose ps
docker compose logs --tail 30 backend || true
fail "backend did not become healthy within 60s — see logs above"
