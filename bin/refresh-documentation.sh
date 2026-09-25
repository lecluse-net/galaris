#!/usr/bin/env bash
# Compare prepared repository docs with the live container, then synchronize retrieval.
set -euo pipefail
cd "$(dirname "$0")/.."
expected=$(docker compose "$@" run --rm --no-deps -T -v "$PWD:/repo:ro" -w /repo/back \
  backend python -m app.documentation revision --root /repo)
if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
  echo 'Could not determine the prepared documentation revision.' >&2
  exit 1
fi
docker compose "$@" exec -T backend python -m app.documentation refresh --expected-revision "$expected"
