#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "$0")/.."

compose=(
  docker compose
  -p "${APP_NAME:-galaris}-tests-$$"
  -f compose.test.yaml
)
test_services=(db-test)
run_options=()
if [[ "${BACKEND_TEST_SAMBA:-0}" == 1 ]]; then
  compose+=(-f compose.test.samba.yaml)
  test_services+=(samba-test)
fi
if [[ "${BACKEND_TEST_N8N:-0}" == 1 ]]; then
  compose+=(-f compose.test.n8n.yaml)
  test_services+=(n8n-test)
fi
if [[ -n "${PROCESS_HARNESS_TEST_IMAGE:-}" ]]; then
  compose+=(-f compose.test.process-harness.yaml)
  test_services+=(claude-test)
  run_options+=(--use-aliases)
fi

cleanup() {
  "${compose[@]}" down --remove-orphans --rmi local >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Each invocation owns its project; simultaneous suites must not stop one another.
"${compose[@]}" up --detach --wait --build "${test_services[@]}"
runner_env=()
if [[ "${QUALIFY_PROCESS_PYTHON:-0}" == 1 ]]; then
  runner_env=(-e QUALIFY_PROCESS_PYTHON -e PROCESS_PYTHON_RUNNER_URL -e PROCESS_PYTHON_RUNNER_TOKEN)
fi
"${compose[@]}" run --rm --no-deps "${run_options[@]}" "${runner_env[@]}" -e "PYTHONTRACEMALLOC=${PYTHONTRACEMALLOC:-0}" \
  -e "DBADMIN_LOAD_TEST=${DBADMIN_LOAD_TEST:-0}" -e "DBADMIN_LOAD_ROWS=${DBADMIN_LOAD_ROWS:-100000}" \
  -e "MIXED_LOAD_SECONDS=${MIXED_LOAD_SECONDS:-0}" backend \
  bash -c 'python -m core.dbadmin synchronize --mode test >/tmp/test-dbadmin.log && python tests/prepare_database_template.py && if [[ "${1:-}" == --mutations ]]; then exec python scripts/check_workflow_mutations.py; else exec pytest "$@"; fi' \
  bash "$@"
