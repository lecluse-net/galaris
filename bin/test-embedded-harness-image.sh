#!/usr/bin/env bash
# Exercise one already-built backend image with an isolated database and no external network.
set -euo pipefail
cd "$(dirname "$0")/.."

image=$(docker image inspect --format '{{.Id}}' "${EMBEDDED_HARNESS_IMAGE:?Set EMBEDDED_HARNESS_IMAGE to a local backend image}")
revision=${EMBEDDED_HARNESS_REVISION:?Set EMBEDDED_HARNESS_REVISION to the revision expected in that image}
project="galaris-embedded-image-$$"
report=${EMBEDDED_HARNESS_REPORT_DIR:-"$PWD/artifacts/embedded-harness-image/$project"}
mkdir -p "$report"
owns_network=false
owns_database=false
managed_environment=()
cleanup() {
  local status=$?
  if "$owns_network"; then
    if ((status != 0)) && ((${#managed_environment[@]})); then
      for provider in codex deepseek_harness; do
        docker logs "$project-$provider" > "$report/$provider.log" 2>&1 || true
      done
    fi
    docker rm -f "$project-backend" "$project-codex" "$project-deepseek_harness" >/dev/null 2>&1 || true
  fi
  if "$owns_database"; then
    if ((status != 0)); then
      docker logs "$project-db" > "$report/database.log" 2>&1 || printf 'Could not retain isolated database logs\n' >&2
    fi
    docker rm -f "$project-db" >/dev/null 2>&1 || true
  fi
  if "$owns_network"; then docker network rm "$project" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker network create --internal "$project" >/dev/null
owns_network=true
docker run -d --name "$project-db" --network "$project" --network-alias embedded-harness-db \
  --tmpfs /var/lib/postgresql/data -e POSTGRES_USER=testuser -e POSTGRES_DB=test_db \
  -e POSTGRES_PASSWORD=synthetic-test-password pgvector/pgvector:pg17 >/dev/null
owns_database=true
ready=false
for ((attempt=0; attempt<45; attempt++)); do
  if docker exec "$project-db" pg_isready -h 127.0.0.1 -U testuser -d test_db >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if ! "$ready"; then
  docker logs "$project-db" >&2
  exit 1
fi

if [[ -n ${EMBEDDED_HARNESS_CODEX_IMAGE:-} || -n ${EMBEDDED_HARNESS_DSH_IMAGE:-} ]]; then
  gateway=http://embedded-harness-backend:8000/api
  for provider in codex deepseek_harness; do
    if [[ $provider == codex ]]; then
      ref=${EMBEDDED_HARNESS_CODEX_IMAGE:?Select a local Codex image}
      runtime_options=(--tmpfs /var/lib/codex:mode=1777 -e CODEX_HOME=/var/lib/codex
        -e "GALARIS_LLM_URL=$gateway/llm/openai")
    else
      ref=${EMBEDDED_HARNESS_DSH_IMAGE:?Select a local DeepSeek Harness image}
      runtime_options=(--tmpfs /sessions:mode=1777 -e HARNESS_MODEL=embedded-image-model
        -e "DEEPSEEK_BASE_URL=$gateway/llm/openai" -e "DEEPSEEK_API_KEY=mcp_qualification_$provider")
    fi
    runtime_image=$(docker image inspect --format '{{.Id}}' "$ref")
    managed_environment+=(-e "QUALIFICATION_IMAGE_$provider=$runtime_image")
    docker run --detach --name "$project-$provider" --network "$project" --network-alias "qualification-$provider" \
      --cap-drop ALL --security-opt no-new-privileges --read-only --memory 4g --cpus 2 --pids-limit 256 \
      --tmpfs /tmp:mode=1777 --tmpfs /workspace:mode=1777 \
      -e "GALARIS_MCP_URL=$gateway/mcp/synthetic-$provider" -e "GALARIS_MCP_TOKEN=mcp_qualification_$provider" \
      -e "HARNESS_API_TOKEN=qualification-api-$provider" "${runtime_options[@]}" "$runtime_image" >/dev/null
  done
fi

docker run --rm --name "$project-backend" --network "$project" --network-alias embedded-harness-backend \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /data:mode=1777 --workdir /app \
  --mount "type=bind,src=$PWD/back/scripts/qualify_embedded_harness_image.py,dst=/probe.py,readonly" \
  --mount "type=bind,src=$PWD/e2e/fixtures/browser-token,dst=/run/galaris-browser/token,readonly" \
  -e HOME=/data -e TMPDIR=/data -e XDG_CACHE_HOME=/data/cache -e PYTHONPATH=/app -e PYTHONDONTWRITEBYTECODE=1 \
  -e APP_ENV=test -e POSTGRES_HOST=embedded-harness-db -e POSTGRES_USER=testuser -e POSTGRES_DB=test_db \
  -e BACK_ALLOWED_HOSTS=embedded-harness-backend \
  -e POSTGRES_PASSWORD=synthetic-test-password -e LOGFIRE_SEND_TO_LOGFIRE=false \
  -e AUTH_SECRET_KEY=embedded-harness-qualification-auth-key \
  -e ENCRYPTION_MASTER_KEY=embedded-harness-qualification-encryption-key \
  -e "QUALIFICATION_BACKEND_IMAGE=$image" -e "QUALIFICATION_REVISION=$revision" \
  -e "QUALIFICATION_BATCH_SIZE=${EMBEDDED_HARNESS_LOAD_ROOMS:-0}" \
  "${managed_environment[@]}" \
  --entrypoint bash "$image" -c 'python -m core.dbadmin synchronize --mode test && exec python /probe.py' \
  2>&1 | tee "$report/qualification.log"
printf 'Embedded harness image evidence: %s\n' "$report/qualification.log"
