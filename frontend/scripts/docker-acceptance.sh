#!/usr/bin/env sh
# Isolated Docker acceptance entry point.  It deliberately uses a separate
# Compose project and port so it never touches a developer's running Nexus.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../../.." && pwd)
PROJECT=${NEXUS_E2E_PROJECT:-nexus-e2e}
PORT=${NEXUS_E2E_PORT:-18180}
ARTIFACT_DIR=${NEXUS_E2E_ARTIFACT_DIR:-$HERE/../artifacts/docker-acceptance}
BASE_COMPOSE_FILE=$ROOT/docker-compose.yml
BUILD_COMPOSE_FILE=$ROOT/docker-compose.build.yml
ACCEPTANCE_COMPOSE_FILE=$ROOT/docker-compose.acceptance.yml

# The acceptance stack always builds from this checkout, never from ghcr.io.
compose() {
  docker compose -p "$PROJECT" -f "$BASE_COMPOSE_FILE" -f "$BUILD_COMPOSE_FILE" -f "$ACCEPTANCE_COMPOSE_FILE" "$@"
}

mkdir -p "$ARTIFACT_DIR"
cd "$HERE/.."

export NEXUS_PORT="$PORT"
# Qualification uses its own HTTP listener; never inherit production feed URLs
# or a TLS-only cookie policy from a developer's environment.
export NEXUS_PUBLIC_API_URL="http://127.0.0.1:$PORT/api"
export NEXUS_REFRESH_COOKIE_SECURE=false
export NEXUS_NOVEL_API_PORT=${NEXUS_E2E_API_PORT:-18000}
export NEXUS_WEBHOOK_SECRET=${NEXUS_WEBHOOK_SECRET:-nexus-e2e-webhook-secret}
export NEXUS_NOVEL_SECRET_KEY=${NEXUS_NOVEL_SECRET_KEY:-nexus-e2e-novel-secret}
# Never replace the local stable-image tags during an acceptance build.
export NEXUS_VERSION=${NEXUS_E2E_IMAGE_VERSION:-1.3.0-alpha-acceptance}
E2E_USERNAME=${NEXUS_E2E_USER:-nexus-e2e-admin}
E2E_PASSWORD=${NEXUS_E2E_PASSWORD:-NexusE2E-1234}
# A disposable signer exercises the full package trust/installation path.
# It is scoped to this isolated stack and never used by published images.
public_key=$(node -e 'const {generateKeyPairSync}=require("node:crypto");const fs=require("node:fs");const {publicKey,privateKey}=generateKeyPairSync("ed25519");fs.writeFileSync(process.argv[1],privateKey.export({type:"pkcs8",format:"pem"}),{mode:0o600});process.stdout.write(publicKey.export({type:"spki",format:"der"}).subarray(-32).toString("base64"));' "$ARTIFACT_DIR/plugin-signing.pem")
export NEXUS_PLUGIN_TRUSTED_KEYS="{\"your-publisher\":\"$public_key\"}"
export NEXUS_LOCAL_AI_BASE_URL=http://fixture-source:8090/ai/v1
# A developer's .env may configure paid providers. Qualification must never
# inherit those credentials or dispatch real image/analysis requests.
export NEXUS_ANALYSIS_ENGINE_PROVIDER=fixture
export NEXUS_ANALYSIS_ENGINE_LLM_API_KEY=
export NEXUS_ANALYSIS_ENGINE_IMAGE_ENABLED=false
export NEXUS_ANALYSIS_ENGINE_PIPELINE_VERSION=story-guide-v5-evidence-dossier

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose ps -a >"$ARTIFACT_DIR/compose-ps.txt" 2>&1 || true
    compose logs --no-color >"$ARTIFACT_DIR/compose.log" 2>&1 || true
  fi
  compose down --volumes --remove-orphans
  rm -f "$ARTIFACT_DIR/plugin-signing.pem"
  exit "$status"
}
trap cleanup EXIT INT TERM

compose up --build --detach
# Keep actual image identities with each disposable qualification run.
compose images --format json > "$ARTIFACT_DIR/image-identities.json"
git -C "$ROOT" rev-parse HEAD > "$ARTIFACT_DIR/checkout-revision.txt"
git -C "$ROOT" submodule status > "$ARTIFACT_DIR/submodule-revisions.txt"

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
compose exec -T metadata-api python scripts/check_plugin_runtime.py
compose exec -T metadata-api sh -c 'set -eu; umask 077; trap "rm -f /tmp/acceptance-signing.pem" EXIT; cat > /tmp/acceptance-signing.pem; python source-plugins/sdk.py build source-plugins/references/author-serial --key /tmp/acceptance-signing.pem --output /tmp/acceptance-plugin.zip' < "$ARTIFACT_DIR/plugin-signing.pem"
compose exec -T metadata-api cat /tmp/acceptance-plugin.zip > "$ARTIFACT_DIR/source-package.zip"

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
compose exec -T -e NEXUS_BACKUP_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - < "$ROOT/scripts/companion-acceptance-fixture.py" > "$ARTIFACT_DIR/companion-fixture.json"
compose exec -T -e NEXUS_BACKUP_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - < "$ROOT/scripts/translation-acceptance-fixture.py" > "$ARTIFACT_DIR/translation-fixture.json"
compose exec -T -e NEXUS_BACKUP_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - < "$ROOT/scripts/reading-runs-acceptance-fixture.py" > "$ARTIFACT_DIR/reading-runs-fixture.json"
compose exec -T -e NEXUS_BACKUP_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - < "$ROOT/scripts/provider-usage-acceptance-fixture.py" > "$ARTIFACT_DIR/provider-usage-fixture.json"
compose exec -T -e NEXUS_SOURCE_MIGRATION_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - < "$ROOT/scripts/source-migration-acceptance-fixture.py" > "$ARTIFACT_DIR/source-migration-fixture.json"
compose exec -T -e NEXUS_READER_GUIDE_ACCEPTANCE=1 metadata-api python - metadata < "$ROOT/scripts/reader-guide-acceptance-fixture.py"
compose exec -T -e NEXUS_READER_GUIDE_ACCEPTANCE=1 nexus-analysis-engine python - analysis < "$ROOT/scripts/reader-guide-acceptance-fixture.py"
compose exec -T -e NEXUS_READER_GUIDE_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend < "$ROOT/scripts/reader-guide-acceptance-fixture.py" > "$ARTIFACT_DIR/reader-guide-fixture.json"
compose exec -T -e NEXUS_SMART_SHELF_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - seed < "$ROOT/scripts/smart-shelf-acceptance-fixture.py" > "$ARTIFACT_DIR/smart-shelf-fixture.json"
compose exec -T -e NEXUS_CATALOG_WATCH_ACCEPTANCE=1 metadata-api python - metadata-seed < "$ROOT/scripts/catalog-watch-acceptance-fixture.py" > "$ARTIFACT_DIR/catalog-watch-fixture.json"
NEXUS_E2E_BASE_URL="http://127.0.0.1:$PORT" \
NEXUS_E2E_MODE="${NEXUS_E2E_MODE:-real}" \
NEXUS_E2E_USER="$E2E_USERNAME" \
NEXUS_E2E_PASSWORD="$E2E_PASSWORD" \
NEXUS_E2E_ARTIFACT_DIR="$ARTIFACT_DIR" \
NEXUS_E2E_PLUGIN_PACKAGE="$ARTIFACT_DIR/source-package.zip" \
NEXUS_E2E_COMPANION_FIXTURE="$ARTIFACT_DIR/companion-fixture.json" \
NEXUS_E2E_TRANSLATION_FIXTURE="$ARTIFACT_DIR/translation-fixture.json" \
NEXUS_E2E_READING_RUNS_FIXTURE="$ARTIFACT_DIR/reading-runs-fixture.json" \
NEXUS_E2E_PROVIDER_USAGE_FIXTURE="$ARTIFACT_DIR/provider-usage-fixture.json" \
NEXUS_E2E_SOURCE_MIGRATION_FIXTURE="$ARTIFACT_DIR/source-migration-fixture.json" \
NEXUS_E2E_READER_GUIDE_FIXTURE="$ARTIFACT_DIR/reader-guide-fixture.json" \
NEXUS_E2E_SMART_SHELF_FIXTURE="$ARTIFACT_DIR/smart-shelf-fixture.json" \
PLAYWRIGHT_HTML_OUTPUT_DIR="$ARTIFACT_DIR/playwright-report" \
npx playwright test --config=playwright.docker.config.ts \
  e2e/real-stack-smoke.spec.ts \
  e2e/real-stack-accounts.spec.ts \
  e2e/real-stack-plugins.spec.ts \
  e2e/real-stack-live-search.spec.ts \
  e2e/real-stack-companion.spec.ts \
  e2e/real-stack-translations.spec.ts \
  e2e/real-stack-reading-runs.spec.ts \
  e2e/real-stack-reading-life.spec.ts \
  e2e/real-stack-provider-usage.spec.ts \
  e2e/real-stack-source-migration.spec.ts \
  e2e/real-stack-saved-searches.spec.ts \
  e2e/real-stack-smart-shelves.spec.ts \
  e2e/real-stack-reader-guide.spec.ts \
  e2e/real-stack-downloads.spec.ts \
  e2e/real-stack-preferences.spec.ts \
  e2e/real-stack-provider-audio.spec.ts \
  e2e/real-stack-audio-exports.spec.ts \
  e2e/real-stack-voices.spec.ts

# Run after signed-package installation; use real broker/worker transactions.
NEXUS_E2E_BASE_URL="http://127.0.0.1:$PORT" \
NEXUS_E2E_MODE=real \
NEXUS_E2E_USER="$E2E_USERNAME" \
NEXUS_E2E_PASSWORD="$E2E_PASSWORD" \
NEXUS_E2E_PLUGIN_PACKAGE="$ARTIFACT_DIR/source-package.zip" \
NEXUS_E2E_ARTIFACT_DIR="$ARTIFACT_DIR/plugin-catalog" \
PLAYWRIGHT_HTML_OUTPUT_DIR="$ARTIFACT_DIR/plugin-catalog/playwright-report" \
npx playwright test --config=playwright.docker.config.ts e2e/real-stack-plugin-catalog.spec.ts
compose exec -T -e NEXUS_PLUGIN_CATALOG_ACCEPTANCE=1 metadata-api python - --capture < "$ROOT/scripts/plugin-catalog-acceptance-fixture.py" > "$ARTIFACT_DIR/plugin-catalog-proof.json"

# Real builtin adapter/worker delivery: partial-page resume, own conditional
# validators, definition-scoped publications, and durable control receipts.
NEXUS_E2E_BASE_URL="http://127.0.0.1:$PORT" \
NEXUS_E2E_MODE=real \
NEXUS_E2E_USER="$E2E_USERNAME" \
NEXUS_E2E_PASSWORD="$E2E_PASSWORD" \
NEXUS_E2E_BUILTIN_CATALOG=1 \
NEXUS_E2E_FIXTURE_URL="http://127.0.0.1:${NEXUS_FIXTURE_SOURCE_PORT:-8090}" \
NEXUS_E2E_ARTIFACT_DIR="$ARTIFACT_DIR/builtin-catalog" \
PLAYWRIGHT_HTML_OUTPUT_DIR="$ARTIFACT_DIR/builtin-catalog/playwright-report" \
npx playwright test --config=playwright.docker.config.ts e2e/real-stack-builtin-catalog.spec.ts
compose exec -T -e NEXUS_BUILTIN_CATALOG_ACCEPTANCE=1 metadata-api python - --capture < "$ROOT/scripts/builtin-catalog-acceptance-fixture.py" > "$ARTIFACT_DIR/builtin-catalog-proof.json"

# Account-private inference uses only the explicitly configured synthetic local
# HTTP provider. No shared guide regeneration or native narration is invoked.
compose exec -T -e NEXUS_PRIVATE_GUIDE_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - seed < "$ROOT/scripts/private-guide-acceptance-fixture.py" > "$ARTIFACT_DIR/private-guide-fixture.json"
NEXUS_E2E_BASE_URL="http://127.0.0.1:$PORT" \
NEXUS_E2E_MODE="${NEXUS_E2E_MODE:-real}" \
NEXUS_E2E_USER="$E2E_USERNAME" \
NEXUS_E2E_PASSWORD="$E2E_PASSWORD" \
NEXUS_E2E_PRIVATE_GUIDE_FIXTURE="$ARTIFACT_DIR/private-guide-fixture.json" \
NEXUS_E2E_ARTIFACT_DIR="$ARTIFACT_DIR/private-guide" \
PLAYWRIGHT_HTML_OUTPUT_DIR="$ARTIFACT_DIR/private-guide/playwright-report" \
npx playwright test --config=playwright.docker.config.ts e2e/real-stack-private-guide.spec.ts
compose exec -T -e NEXUS_PRIVATE_GUIDE_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - capture < "$ROOT/scripts/private-guide-acceptance-fixture.py" > "$ARTIFACT_DIR/private-guide-proof.json"



# Activate through the actual browser, then commit new catalog facts. The
# worker must distinguish a refreshed baseline story from the newly found one.
# The populated backup fixture establishes hidden-content preferences first;
# changing them after activation must (correctly) invalidate the prepared query.
if [ "${NEXUS_E2E_BACKUP_REHEARSAL:-0}" = 1 ]; then
  compose exec -T -e NEXUS_BACKUP_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - seed < "$ROOT/scripts/backup-acceptance-fixture.py"
fi
# Review after the backup fixture establishes account visibility, and before
# watch activation. Reviewed alias changes must not invalidate either preview.
compose exec -T -e NEXUS_CATALOG_REVIEW_ACCEPTANCE=1 metadata-api python - metadata-seed < "$ROOT/scripts/catalog-review-acceptance-fixture.py" > "$ARTIFACT_DIR/catalog-review-fixture.json"
catalog_review_proof() {
  compose cp "$ARTIFACT_DIR/catalog-review-fixture.json" metadata-api:/tmp/nexus-catalog-review-fixture.json
  compose cp "$ARTIFACT_DIR/catalog-review-fixture.json" novel-api:/tmp/nexus-catalog-review-fixture.json
}
catalog_review_browser() {
  NEXUS_E2E_BASE_URL="http://127.0.0.1:$PORT" \
  NEXUS_E2E_MODE="${NEXUS_E2E_MODE:-real}" \
  NEXUS_E2E_USER="$E2E_USERNAME" \
  NEXUS_E2E_PASSWORD="$E2E_PASSWORD" \
  NEXUS_E2E_ARTIFACT_DIR="$ARTIFACT_DIR/reviews-$1" \
  NEXUS_E2E_CATALOG_REVIEW_FIXTURE="$ARTIFACT_DIR/catalog-review-fixture.json" \
  NEXUS_E2E_CATALOG_REVIEW_PHASE="$1" \
  PLAYWRIGHT_HTML_OUTPUT_DIR="$ARTIFACT_DIR/reviews-$1/playwright-report" \
  npx playwright test --config=playwright.docker.config.ts e2e/real-stack-catalog-review.spec.ts
}
catalog_review_proof
compose exec -T -e NEXUS_CATALOG_REVIEW_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-seed < "$ROOT/scripts/catalog-review-acceptance-fixture.py"
catalog_review_browser apply
compose exec -T -e NEXUS_CATALOG_REVIEW_ACCEPTANCE=1 metadata-api python - metadata-verify < "$ROOT/scripts/catalog-review-acceptance-fixture.py"
compose exec -T -e NEXUS_CATALOG_REVIEW_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-verify < "$ROOT/scripts/catalog-review-acceptance-fixture.py"
for catalog_phase in activate verify; do
  if [ "$catalog_phase" = verify ]; then
    compose exec -T -e NEXUS_CATALOG_WATCH_ACCEPTANCE=1 metadata-api python - metadata-add < "$ROOT/scripts/catalog-watch-acceptance-fixture.py"
  fi
  NEXUS_E2E_BASE_URL="http://127.0.0.1:$PORT" \
  NEXUS_E2E_MODE="${NEXUS_E2E_MODE:-real}" \
  NEXUS_E2E_USER="$E2E_USERNAME" \
  NEXUS_E2E_PASSWORD="$E2E_PASSWORD" \
  NEXUS_E2E_ARTIFACT_DIR="$ARTIFACT_DIR/catalog-$catalog_phase" \
  NEXUS_E2E_CATALOG_WATCH_FIXTURE="$ARTIFACT_DIR/catalog-watch-fixture.json" \
  NEXUS_E2E_CATALOG_PHASE="$catalog_phase" \
  PLAYWRIGHT_HTML_OUTPUT_DIR="$ARTIFACT_DIR/catalog-$catalog_phase/playwright-report" \
  npx playwright test --config=playwright.docker.config.ts e2e/real-stack-catalog-watches.spec.ts
done
compose stop novel-worker
compose exec -T -e NEXUS_CATALOG_WATCH_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-ranked-idle < "$ROOT/scripts/catalog-watch-acceptance-fixture.py"
compose start novel-worker
compose exec -T -e NEXUS_CATALOG_WATCH_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-seed < "$ROOT/scripts/catalog-watch-acceptance-fixture.py"

if [ "${NEXUS_E2E_BACKUP_REHEARSAL:-0}" = 1 ]; then
  # This script owns a disposable Compose project, so replacing its data is
  # intentional. Never run this section against a reader's installation.
  export COMPOSE_PROJECT_NAME="$PROJECT"
  export COMPOSE_FILE="$BASE_COMPOSE_FILE:$BUILD_COMPOSE_FILE:$ACCEPTANCE_COMPOSE_FILE"
  backup_dir="$ARTIFACT_DIR/backup-rehearsal"
  "$ROOT/scripts/backup.sh" --output "$backup_dir"
  archive=$(find "$backup_dir" -maxdepth 1 -name 'nexus-*.tar.gz' | sort | tail -n 1)
  "$ROOT/scripts/restore.sh" --validate-only "$archive"
  "$ROOT/scripts/restore.sh" --yes "$archive"
  compose exec -T -e NEXUS_BACKUP_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - verify < "$ROOT/scripts/backup-acceptance-fixture.py"
  compose exec -T -e NEXUS_SOURCE_MIGRATION_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - --verify < "$ROOT/scripts/source-migration-acceptance-fixture.py"
  compose exec -T -e NEXUS_READER_GUIDE_ACCEPTANCE=1 metadata-api python - metadata-verify < "$ROOT/scripts/reader-guide-acceptance-fixture.py"
  compose exec -T -e NEXUS_READER_GUIDE_ACCEPTANCE=1 nexus-analysis-engine python - analysis-verify < "$ROOT/scripts/reader-guide-acceptance-fixture.py"
  compose exec -T -e NEXUS_READER_GUIDE_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-verify < "$ROOT/scripts/reader-guide-acceptance-fixture.py"
  compose exec -T -e NEXUS_SMART_SHELF_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - verify < "$ROOT/scripts/smart-shelf-acceptance-fixture.py"
  compose exec -T -e NEXUS_CATALOG_WATCH_ACCEPTANCE=1 metadata-api python - metadata-verify < "$ROOT/scripts/catalog-watch-acceptance-fixture.py"
  compose exec -T -e NEXUS_CATALOG_WATCH_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-verify < "$ROOT/scripts/catalog-watch-acceptance-fixture.py"
  compose exec -T -e NEXUS_CATALOG_WATCH_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-verify-live < "$ROOT/scripts/catalog-watch-acceptance-fixture.py"
  catalog_review_proof
  compose exec -T -e NEXUS_CATALOG_REVIEW_ACCEPTANCE=1 metadata-api python - metadata-verify < "$ROOT/scripts/catalog-review-acceptance-fixture.py"
  compose exec -T -e NEXUS_CATALOG_REVIEW_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-verify < "$ROOT/scripts/catalog-review-acceptance-fixture.py"
  compose exec -T -e NEXUS_CATALOG_REVIEW_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - backend-verify-live < "$ROOT/scripts/catalog-review-acceptance-fixture.py"
  catalog_review_browser verify
  compose cp "$ARTIFACT_DIR/plugin-catalog-proof.json" metadata-api:/tmp/nexus-plugin-catalog-proof.json
  compose exec -T -e NEXUS_PLUGIN_CATALOG_ACCEPTANCE=1 metadata-api python - --verify < "$ROOT/scripts/plugin-catalog-acceptance-fixture.py"
  compose cp "$ARTIFACT_DIR/builtin-catalog-proof.json" metadata-api:/tmp/nexus-builtin-catalog-proof.json
  compose exec -T -e NEXUS_BUILTIN_CATALOG_ACCEPTANCE=1 metadata-api python - --verify < "$ROOT/scripts/builtin-catalog-acceptance-fixture.py"
  compose cp "$ARTIFACT_DIR/private-guide-proof.json" novel-api:/tmp/nexus-private-guide-proof.json
  compose exec -T -e NEXUS_PRIVATE_GUIDE_ACCEPTANCE=1 novel-api /app/backend/.venv/bin/python - verify < "$ROOT/scripts/private-guide-acceptance-fixture.py"

  compose exec -T -e NEXUS_BACKUP_ACCEPTANCE=1 metadata-api sh -c 'cat > /tmp/nexus-plugin-restore.py; python /tmp/nexus-plugin-restore.py; rm -f /tmp/nexus-plugin-restore.py' < "$ROOT/scripts/plugin-acceptance-fixture.py"
  compose stop nexus-analysis-engine
  compose rm -f nexus-analysis-engine
  "$ROOT/scripts/backup.sh" --output "$backup_dir/no-analysis"
  archive=$(find "$backup_dir/no-analysis" -maxdepth 1 -name 'nexus-*.tar.gz' | sort | tail -n 1)
  "$ROOT/scripts/restore.sh" --validate-only "$archive"
fi
