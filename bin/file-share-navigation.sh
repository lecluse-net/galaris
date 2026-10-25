#!/usr/bin/env bash
# Fresh runtimes, synthetic corpus, no Task creation and no messages to any user.
set -euo pipefail
cd "$(dirname "$0")/.."
source_root=$PWD
phase=${1:-pilot}
case "$phase" in pilot|decision) ;; *) echo 'Usage: make file-share-navigation ARGS="pilot|decision <model-code> [upstream]"' >&2; exit 2 ;; esac
model=${2:?Pass the configured development model code after the phase}
upstream=${3:-deepinfra}
backend_image=${NAVIGATION_BACKEND_IMAGE:-galaris-backend:latest}
hermes_image=${NAVIGATION_HERMES_IMAGE:-$(sed -n 's/^ARG HERMES_IMAGE=//p' back/bridge/hermes/default-agent/Dockerfile)}
if ! docker image inspect "$hermes_image" >/dev/null 2>&1; then docker pull "$hermes_image"; fi
backend_digest=$(docker image inspect "$backend_image" --format '{{.Id}}')
hermes_digest=$(docker image inspect "$hermes_image" --format '{{.Id}}')
revision=$(git rev-parse HEAD)
campaign_name="$(date -u +%Y%m%dT%H%M%SZ)-$phase-$$"
campaign="$source_root/artifacts/file-share-navigation/$campaign_name"
private=$(mktemp -d)
network="galaris-navigation-$$"
service="galaris-navigation-service-$$"
runtime="galaris-navigation-runtime-$$"
cleanup() {
    if [[ -d $campaign ]]; then docker logs "$service" > "$campaign/service.log" 2>&1 || true; fi
    docker rm -f "$runtime" "$service" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    rm -rf "$private"
}
trap cleanup EXIT
umask 077
mkdir -p "$private/requests" "$source_root/artifacts/file-share-navigation"
git ls-files -z --cached --others --exclude-standard -- back Makefile bin/file-share-navigation.sh \
    | tar --null -T - -czf "$private/source.tar.gz"
mkdir -p "$private/source"
tar -xzf "$private/source.tar.gz" -C "$private/source"
frozen_source="$private/source/back"
chmod 644 "$frozen_source/scripts/file_share_navigation/hermes_run.py"
# stdout goes directly to a private temporary file. Never enable shell tracing.
docker compose exec -T backend python -m scripts.file_share_navigation.credentials "$model" "$upstream" > "$private/config.json"
repetitions=5
if [[ $phase == pilot ]]; then repetitions=1; fi
controller() {
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
        --user "$(id -u):$(id -g)" --tmpfs /tmp:mode=1777,size=64m \
        -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/source -e APP_ENV=dev \
        --mount "type=bind,src=$frozen_source,dst=/source,readonly" \
        --mount "type=bind,src=$source_root/artifacts/file-share-navigation,dst=/output" \
        --mount "type=bind,src=$private,dst=/private" \
        --workdir /source --entrypoint /app/.venv/bin/python "$backend_digest" "$@"
}
controller -m scripts.file_share_navigation generate "/output/$campaign_name" --phase "$phase" --repetitions "$repetitions"
controller -m scripts.file_share_navigation.prepare "/output/$campaign_name" /private "$backend_digest" "$hermes_digest" "$revision"
cp "$private/source.tar.gz" "$campaign/source.tar.gz"
docker network create --internal "$network" >/dev/null
# Only the relay has upstream network access. The candidate has only the internal network.
docker create --name "$service" --network bridge --read-only --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" \
    --memory 2g --cpus 2 --pids-limit 128 --tmpfs /tmp:mode=1777,size=128m \
    -e APP_ENV=dev -e ENCRYPTION_MASTER_KEY=MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA= \
    -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/source \
    --mount "type=bind,src=$frozen_source,dst=/source,readonly" \
    --mount "type=bind,src=$campaign,dst=/campaign" \
    --mount "type=bind,src=$private,dst=/credentials,readonly" \
    --mount "type=bind,src=$private,dst=/controls,readonly" \
    --workdir /source --entrypoint /app/.venv/bin/python "$backend_digest" \
    -m scripts.file_share_navigation.service >/dev/null
docker network connect --alias navigation-service "$network" "$service"
docker start "$service" >/dev/null
ready=false
for attempt in {1..30}; do
    if [[ $(docker inspect "$service" --format '{{.State.Running}}') != true ]]; then break; fi
    if docker exec "$service" /app/.venv/bin/python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8099/health",timeout=1)' >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
done
if [[ $ready != true ]]; then
    docker logs "$service" > "$campaign/service.log" 2>&1
    echo "Campaign service failed; see $campaign/service.log" >&2
    exit 1
fi
while IFS=$'\t' read -r run arm; do
    echo "Navigation $phase: $run"
    result="$campaign/results/$run"
    mkdir -p "$result"
    # Hermes' pinned uv environment contains root-owned package-cache links.
    # Its root UID has no capabilities and only this empty result directory is writable.
    chmod 777 "$result"
    corpus_mount=()
    if [[ $arm == filesystem ]]; then corpus_mount=(--mount "type=bind,src=$campaign/corpus,dst=/corpus,readonly"); fi
    # Only the driver, current prompt and empty current result directory are shared.
    if ! docker run --rm -i --name "$runtime" --network "$network" --read-only --cap-drop ALL \
        --security-opt no-new-privileges --memory 4g --cpus 2 --pids-limit 128 \
        --user 0:0 --tmpfs /tmp:mode=1777,size=128m --tmpfs /workspace:mode=1777,size=16m \
        -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp/home -e HERMES_HOME=/tmp/hermes \
        --mount "type=bind,src=$frozen_source/scripts/file_share_navigation/hermes_run.py,dst=/driver.py,readonly" \
        --mount "type=bind,src=$result,dst=/result" "${corpus_mount[@]}" \
        --entrypoint /opt/hermes/.venv/bin/python "$hermes_digest" /driver.py \
        < "$private/requests/$run.json" > "$result/runtime.log" 2>&1; then
        echo "Runtime failed; retaining evidence in $result" >&2
        exit 1
    fi
done < "$private/runs.tsv"
controller -m scripts.file_share_navigation report "/output/$campaign_name" > "$campaign/report.log"
echo "Campaign completed: $campaign/summary.json"
