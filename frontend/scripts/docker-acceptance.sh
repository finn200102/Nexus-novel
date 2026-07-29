#!/usr/bin/env sh
# Isolated Docker acceptance entry point.  It deliberately uses a separate
# Compose project and port so it never touches a developer's running Nexus.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../../.." && pwd)
PROJECT=${NEXUS_E2E_PROJECT:-nexus-e2e}
PORT=${NEXUS_E2E_PORT:-18180}

export NEXUS_PORT="$PORT"
export NEXUS_NOVEL_API_PORT=${NEXUS_E2E_API_PORT:-18000}
export NEXUS_WEBHOOK_SECRET=${NEXUS_WEBHOOK_SECRET:-nexus-e2e-webhook-secret}
export NEXUS_NOVEL_SECRET_KEY=${NEXUS_NOVEL_SECRET_KEY:-nexus-e2e-novel-secret}

cleanup() {
  docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" down --volumes --remove-orphans
}
trap cleanup EXIT INT TERM

docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" up --build --detach

deadline=$(( $(date +%s) + 180 ))
until curl --fail --silent "http://127.0.0.1:$PORT/" >/dev/null; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" logs --no-color
    exit 1
  fi
  sleep 2
done

# The browser suite uses deterministic fixture responses for source and TTS
# calls, while the stack itself is real: Compose migrations, API startup,
# health checks, and both worker processes must all be alive first.
NEXUS_E2E_BASE_URL="http://127.0.0.1:$PORT" npm run test:e2e:docker
