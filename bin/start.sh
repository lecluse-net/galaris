#!/usr/bin/env bash
# Exit 10 requests one full update; inspection errors must stop the command.
set -euo pipefail
compose=(docker compose "$@")

needs_update() {
    echo "ℹ️  $1; running a full update."
    exit 10
}

services=$("${compose[@]}" config --services) || exit 1
if [[ -z "$services" ]]; then
    echo 'No enabled Compose services found.' >&2
    exit 1
fi
while IFS= read -r service; do
    containers=$("${compose[@]}" ps --all --quiet "$service") || exit 1
    found=false
    while IFS= read -r container; do
        [[ -n "$container" ]] || continue
        # Only inspect state and the one-off label; never print environment secrets.
        state=$(docker inspect --format '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{index .Config.Labels "com.docker.compose.oneoff"}}' "$container") || exit 1
        IFS='|' read -r status exit_code oom health oneoff <<< "$state"
        [[ "${oneoff,,}" != true ]] || continue
        found=true
        [[ "$oom" != true ]] || needs_update "$service was killed by an out-of-memory condition"
        case "$status" in
            running)
                [[ "$health" != unhealthy ]] || needs_update "$service is unhealthy"
                ;;
            exited)
                # Docker stop can leave a signal exit code. Old health results
                # do not describe a stopped container. Initializers exit with 0.
                case "$exit_code" in
                    0|137|143) ;;
                    *) needs_update "$service exited with an error" ;;
                esac
                ;;
            *) needs_update "$service is not reusable ($status)" ;;
        esac
    done <<< "$containers"
    [[ "$found" == true ]] || needs_update "$service has no existing container"
done <<< "$services"

echo '🐳 Starting existing containers without building...'
# Older Compose versions lack `start --wait`. These flags preserve existing
# containers and images while retaining dependency ordering and readiness checks.
if ! "${compose[@]}" up -d --no-build --no-recreate --pull never --wait --wait-timeout 300; then
    # Do not attempt a build if the daemon became unavailable during startup.
    docker info >/dev/null || exit 1
    needs_update 'Existing containers did not become ready'
fi
