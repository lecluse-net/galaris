#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
project="galaris-front-tests-${GITHUB_RUN_ID:-local}-$$"
export GALARIS_FRONT_TEST_ARTIFACT_DIR="$PWD/artifacts/front-components/$project"
export GALARIS_FRONT_TEST_SOURCE_DIR
GALARIS_FRONT_TEST_SOURCE_DIR=$(mktemp -d "/tmp/$project.XXXXXX")
# The frontend image runs as node, whose UID may differ from the CI checkout owner.
chmod 755 "$GALARIS_FRONT_TEST_SOURCE_DIR"
compose=(docker compose -p "$project" -f compose.front-tests.yaml)
mkdir -p "$GALARIS_FRONT_TEST_ARTIFACT_DIR"
cleanup() {
  "${compose[@]}" logs --no-color frontend > "$GALARIS_FRONT_TEST_ARTIFACT_DIR/frontend.log" 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans --rmi local >/dev/null 2>&1 || true
  rm -rf "$GALARIS_FRONT_TEST_SOURCE_DIR"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Freeze the code under test: concurrent edits must not reload an active browser.
tar -C front --exclude=node_modules --exclude=dist --exclude=dev-dist -cf - . |
  tar -C "$GALARIS_FRONT_TEST_SOURCE_DIR" -xf -
# Nested volume mountpoint, including on a fresh checkout.
mkdir -p "$GALARIS_FRONT_TEST_SOURCE_DIR/node_modules"
"${compose[@]}" build
"${compose[@]}" up -d --wait frontend
"${compose[@]}" run --rm --no-deps runner npx playwright test --config components/playwright.config.mjs "$@"
