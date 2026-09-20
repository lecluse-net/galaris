#!/usr/bin/env bash
# Exercise the real production installation with new, disposable Docker volumes.
set -euo pipefail
cd "$(dirname "$0")/.."
source_root=$PWD
source bin/validation-source.sh
mkdir -p artifacts/install
run_dir=$(mktemp -d "$source_root/artifacts/install/run.XXXXXX")
snapshot="$run_dir/source"
project="galaris-install-${run_dir##*.}"
project=${project,,}
port=${INSTALL_TEST_PORT:-18484}
validation_archive "$source_root" "$run_dir/source.tar"
git clone --quiet --shared --no-checkout "$source_root" "$snapshot"
tar -xf "$run_dir/source.tar" -C "$snapshot"
cd "$snapshot"
# Do not inherit the operator's deployment settings into the disposable stack.
unset APP_NAME APP_ENV INSTALL_PORT VERSION RELEASE_DIR GIT_UPDATE MAKEOVERRIDES COMPOSE_FILE COMPOSE_PROJECT_NAME
for setting in ${!POSTGRES_@} ${!WEBRTC_TURN_@}; do unset "$setting"; done
export MAKEFLAGS=
compose=(docker compose -p "$project" -f compose.yaml -f compose.postgres.yaml -f compose.turn.yaml -f compose.override.yaml)
cleanup() {
    local status=$?
    "${compose[@]}" logs --no-color backend > "$run_dir/backend.log" 2>&1 || true
    "${compose[@]}" down --volumes --remove-orphans --rmi local > "$run_dir/cleanup.log" 2>&1 || true
    if (( status != 0 )); then
        printf 'FAIL: installation test (exit %s); inspect logs in %s\n' "$status" "$run_dir" | tee "$run_dir/summary.txt"
    fi
}
printf 'Installation test: %s\n' "$run_dir"
make install POSTGRES_MODE=embedded INSTALL_PORT="$port" > "$run_dir/install.log" 2>&1
sed -i "s/^APP_NAME=.*/APP_NAME=$project/" .env
# TURN uses host networking: reserve separate test ports from deployed instances.
printf '\nWEBRTC_TURN_PORT=13479\nWEBRTC_TURN_MIN_PORT=57000\nWEBRTC_TURN_MAX_PORT=57100\n' >> .env
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
make start > "$run_dir/start.log" 2>&1
curl --fail --silent "http://localhost:$port/api/health/ready" > "$run_dir/ready.json"
curl --fail --silent "http://localhost:$port/" > "$run_dir/index.html"
"${compose[@]}" exec -T browser-executor node --input-type=module - "http://localhost:$port" \
    < bin/test-initial-admin.mjs > "$run_dir/initial-admin.log" 2>&1
"${compose[@]}" ps --all --quiet | sort > "$run_dir/before.ids"
make stop > "$run_dir/stop.log" 2>&1
make start > "$run_dir/restart.log" 2>&1
"${compose[@]}" ps --all --quiet | sort > "$run_dir/after.ids"
cmp "$run_dir/before.ids" "$run_dir/after.ids"
curl --fail --silent "http://localhost:$port/api/health/ready" > "$run_dir/restarted-ready.json"
echo 'PASS: fresh installation, first administrator registration/login, HTTP readiness and stop/start preserving containers.' | tee "$run_dir/summary.txt"
