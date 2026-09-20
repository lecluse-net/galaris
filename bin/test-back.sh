#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "$0")/.."

compose=(
  docker compose
  -p "${APP_NAME:-galaris}-tests-$$"
  -f compose.test.yaml
)

cleanup() {
  "${compose[@]}" down --remove-orphans --rmi local >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Each invocation owns its project; simultaneous suites must not stop one another.
"${compose[@]}" up --detach --wait db-test
"${compose[@]}" run --rm --no-deps -e "PYTHONTRACEMALLOC=${PYTHONTRACEMALLOC:-0}" \
  -e "DBADMIN_LOAD_TEST=${DBADMIN_LOAD_TEST:-0}" -e "DBADMIN_LOAD_ROWS=${DBADMIN_LOAD_ROWS:-100000}" \
  -e "MIXED_LOAD_SECONDS=${MIXED_LOAD_SECONDS:-0}" backend \
  bash -c 'python -m core.dbadmin synchronize --mode test >/tmp/test-dbadmin.log && python tests/prepare_database_template.py && if [[ "${1:-}" == --mutations ]]; then exec python scripts/check_workflow_mutations.py; else exec pytest "$@"; fi' \
  bash "$@"
