#!/usr/bin/env bash
# Compare prepared repository docs with the live container, then synchronize retrieval.
set -euo pipefail
cd "$(dirname "$0")/.."
expected=$(bash bin/documentation.sh revision)
if [[ ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
  echo 'Could not determine the prepared documentation revision.' >&2
  exit 1
fi
docker compose "$@" exec -T backend python -m app.documentation refresh --expected-revision "$expected"
