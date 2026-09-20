#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
image_tag="galaris-focus-gates-${CI_JOB_ID:-local}-$$"
trap 'docker image rm "$image_tag" >/dev/null 2>&1 || true' EXIT
docker build -t "$image_tag" e2e
docker run --rm --network none -v "$PWD/front/browser-tests/playwright.config.mjs:/component-config.mjs:ro" \
  "$image_tag" node check-focus-gates.mjs
