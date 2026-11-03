#!/usr/bin/env bash
# Exercise the shipped SSH runtime, never a different Python distribution.
set -euo pipefail
cd "$(dirname "$0")/.."
image=${SSH_EXECUTOR_IMAGE:-}
owned_image=""
cleanup() {
  if [[ -n "$owned_image" ]]; then docker image rm "$owned_image" >/dev/null; fi
}
trap cleanup EXIT
if [[ -z "$image" ]]; then
  owned_image="galaris-ssh-tests-$$"
  docker build --build-context console_assets=./back/app/console/assets -t "$owned_image" ssh-executor
  image=$(docker image inspect --format '{{.Id}}' "$owned_image")
fi
docker run --rm --network none --user 0:0 --entrypoint python3 \
  -v "$PWD/ssh-executor/tests:/opt/galaris-executor/tests:ro" \
  "$image" -m unittest discover -s /opt/galaris-executor/tests -v
