#!/usr/bin/env bash
# Actual IDE and SSH tunnel on synthetic disposable targets; freeze inputs first.
set -euo pipefail
cd "$(dirname "$0")/.."
source bin/validation-source.sh
project="galaris-code-browser-$$"
work=$(mktemp -d "${TMPDIR:-/tmp}/$project.XXXXXX")
export CODE_TEST_SOURCE_DIR="$work/source"
export CODE_TEST_ARTIFACT_DIR="$PWD/artifacts/code-runtime/$project"
mkdir -p "$CODE_TEST_SOURCE_DIR" "$CODE_TEST_ARTIFACT_DIR"
chmod 755 "$work" "$CODE_TEST_SOURCE_DIR"
validation_archive "$PWD" "$work/source.tar"
tar -C "$CODE_TEST_SOURCE_DIR" -xf "$work/source.tar"
# Reproduce the private modes used by the real SFTP deployment bundle.
chmod 700 "$CODE_TEST_SOURCE_DIR/code-executor/extension"
chmod 600 "$CODE_TEST_SOURCE_DIR/code-executor/extension/"*
compose=(docker compose -p "$project" -f "$CODE_TEST_SOURCE_DIR/compose.code-tests.yaml")
cleanup() {
  "${compose[@]}" logs --no-color fixture > "$CODE_TEST_ARTIFACT_DIR/fixture.log" 2>&1 || true
  "${compose[@]}" logs --no-color gateway > "$CODE_TEST_ARTIFACT_DIR/gateway.log" 2>&1 || true
  "${compose[@]}" logs --no-color proxy dev-proxy > "$CODE_TEST_ARTIFACT_DIR/proxy.log" 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans --rmi local >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"${compose[@]}" up -d --build --wait fixture
"${compose[@]}" run --rm --build --no-deps runner
"${compose[@]}" run --rm --build --no-deps transport
"${compose[@]}" up -d --build --wait proxy
"${compose[@]}" run --rm --build --no-deps gateway-runner
# Both proxies must exercise the same live backend and ephemeral database. A
# repeated --build may otherwise recreate dependencies with a fresh fixture process.
"${compose[@]}" up -d --build --wait --no-recreate dev-proxy
"${compose[@]}" run --rm --build --no-deps dev-gateway-runner
