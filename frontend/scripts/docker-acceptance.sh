#!/usr/bin/env sh
# Isolated Docker acceptance entry point.  It deliberately uses a separate
# Compose project and port so it never touches a developer's running Nexus.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../../.." && pwd)
PROJECT=${NEXUS_E2E_PROJECT:-nexus-e2e}
PORT=${NEXUS_E2E_PORT:-18180}
ARTIFACT_DIR=${NEXUS_E2E_ARTIFACT_DIR:-$HERE/../artifacts/docker-acceptance}
COMPOSE_FILE=$ROOT/docker-compose.yml
BUILD_COMPOSE_FILE=$ROOT/docker-compose.build.yml
ACCEPTANCE_COMPOSE_FILE=$ROOT/docker-compose.acceptance.yml

# The acceptance stack always builds from this checkout, never from ghcr.io.
compose() {
  docker compose -p "$PROJECT" -f "$COMPOSE_FILE" -f "$BUILD_COMPOSE_FILE" -f "$ACCEPTANCE_COMPOSE_FILE" "$@"
}

mkdir -p "$ARTIFACT_DIR"
cd "$HERE/.."

export NEXUS_PORT="$PORT"
export NEXUS_NOVEL_API_PORT=${NEXUS_E2E_API_PORT:-18000}
export NEXUS_WEBHOOK_SECRET=${NEXUS_WEBHOOK_SECRET:-nexus-e2e-webhook-secret}
export NEXUS_NOVEL_SECRET_KEY=${NEXUS_NOVEL_SECRET_KEY:-nexus-e2e-novel-secret}
E2E_USERNAME=${NEXUS_E2E_USER:-nexus-e2e-admin}
E2E_PASSWORD=${NEXUS_E2E_PASSWORD:-NexusE2E-1234}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose ps -a >"$ARTIFACT_DIR/compose-ps.txt" 2>&1 || true
    compose logs --no-color >"$ARTIFACT_DIR/compose.log" 2>&1 || true
  fi
  compose down --volumes --remove-orphans
  exit "$status"
}
trap cleanup EXIT INT TERM

compose up --build --detach

deadline=$(( $(date +%s) + ${NEXUS_E2E_READY_TIMEOUT_SECONDS:-300} ))
services=$(compose config --services)
until [ -n "$services" ]; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    exit 1
  fi
  sleep 2
done

# Wait for every declared service, not only the HTTP frontend.  Worker
# healthchecks intentionally mean “the worker process is alive”; APIs and
# databases additionally report their readiness through Compose healthchecks.
all_healthy=false
while [ "$all_healthy" != true ]; do
  all_healthy=true
  for service in $services; do
    container=$(compose ps -aq "$service" | head -n 1)
    if [ -z "$container" ]; then
      all_healthy=false
      continue
    fi
    state=$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container" 2>/dev/null || true)
    if [ "$state" != running ] || [ "$health" != healthy ]; then
      all_healthy=false
    fi
  done
  if [ "$all_healthy" = true ]; then
    break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    exit 1
  fi
  sleep 2
done

until curl --fail --silent "http://127.0.0.1:$PORT/" >/dev/null; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    exit 1
  fi
  sleep 2
done
# The same health route the published-stack smoke check uses, through the proxy.
curl --fail --silent --show-error "http://127.0.0.1:$PORT/api/health" >/dev/null

# Create a disposable administrator through the real API.  Each isolated
# Compose project begins with empty volumes, so this account never touches a
# developer's database and is the API's first (administrator) user.
signup_status=$(curl --silent --show-error --output "$ARTIFACT_DIR/signup.json" \
  --write-out '%{http_code}' \
  --header 'Content-Type: application/json' \
  --data "{\"username\":\"$E2E_USERNAME\",\"password\":\"$E2E_PASSWORD\"}" \
  "http://127.0.0.1:${NEXUS_NOVEL_API_PORT}/auth/signup")
if [ "$signup_status" != 201 ] && [ "$signup_status" != 400 ]; then
  echo "Could not seed the real-stack acceptance user (HTTP $signup_status)." >&2
  exit 1
fi

# A real user starts without a library.  Create one through the authenticated
# public API so the browser workflows exercise the normal first-run state
# rather than relying on hidden development fixtures.
e2e_token=$(sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p' "$ARTIFACT_DIR/signup.json" | head -n 1)
if [ -z "$e2e_token" ]; then
  login_status=$(curl --silent --show-error --output "$ARTIFACT_DIR/login.json" \
    --write-out '%{http_code}' \
    --header 'Content-Type: application/json' \
    --data "{\"username\":\"$E2E_USERNAME\",\"password\":\"$E2E_PASSWORD\"}" \
    "http://127.0.0.1:${NEXUS_NOVEL_API_PORT}/auth/login")
  if [ "$login_status" != 200 ]; then
    echo "Could not authenticate the real-stack acceptance user (HTTP $login_status)." >&2
    exit 1
  fi
  e2e_token=$(sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p' "$ARTIFACT_DIR/login.json" | head -n 1)
fi
if [ -z "$e2e_token" ]; then
  echo "The real-stack acceptance user did not receive an access token." >&2
  exit 1
fi

library_status=$(curl --silent --show-error --output "$ARTIFACT_DIR/library.json" \
  --write-out '%{http_code}' \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $e2e_token" \
  --data '{"name":"Acceptance Library"}' \
  "http://127.0.0.1:${NEXUS_NOVEL_API_PORT}/library/")
if [ "$library_status" != 201 ] && [ "$library_status" != 400 ]; then
  echo "Could not seed the real-stack acceptance library (HTTP $library_status)." >&2
  exit 1
fi

# The real API authentication smoke always runs. Existing mocked browser
# scenarios remain complementary component coverage; they are not presented as
# the authority for service/worker behavior.
NEXUS_E2E_BASE_URL="http://127.0.0.1:$PORT" \
NEXUS_E2E_MODE="${NEXUS_E2E_MODE:-real}" \
NEXUS_E2E_USER="$E2E_USERNAME" \
NEXUS_E2E_PASSWORD="$E2E_PASSWORD" \
NEXUS_E2E_ARTIFACT_DIR="$ARTIFACT_DIR" \
PLAYWRIGHT_HTML_OUTPUT_DIR="$ARTIFACT_DIR/playwright-report" \
npx playwright test --config=playwright.docker.config.ts \
  e2e/real-stack-smoke.spec.ts \
  e2e/real-stack-downloads.spec.ts
