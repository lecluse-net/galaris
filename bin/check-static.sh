#!/usr/bin/env bash
# Static gates run in disposable build images; no development stack is required.
set -euo pipefail
cd "$(dirname "$0")/.."
tag="galaris-static-${CI_JOB_ID:-local}-$$"
cleanup() { docker image rm "$tag-back" "$tag-front" "$tag-browser" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker build --build-context harness_manager=./harness_manager \
  --build-context product_docs=./docs --build-context project_docs=./project \
  --target builder -t "$tag-back" back
docker run --rm -e APP_ENV=test -e AUTH_SECRET_KEY=ci-auth-secret-ci-auth-secret-0001 \
  -e BROWSER_EXECUTOR_TOKEN=ci-browser-token-ci-browser-00001 \
  -e ENCRYPTION_MASTER_KEY=ci-encryption-secret-ci-encryption-01 "$tag-back" python -m pyright
docker run --rm "$tag-back" ruff check app core bridge scripts main.py
docker run --rm "$tag-back" python scripts/check_format.py --check
docker run --rm -v "$PWD:/repo" -w /repo "$tag-back" python back/scripts/project_context.py --root /repo --check
docker run --rm -v "$PWD:/repo" -w /repo "$tag-back" python back/scripts/architecture_check.py --root /repo
docker run --rm --network none -e ENCRYPTION_MASTER_KEY=documentation-offline-check-key-0001 \
  "$tag-back" python -m app.documentation check
docker build --target build-stage -t "$tag-front" front
docker run --rm -v "$PWD:/repo:ro" "$tag-front" node scripts/navigation-context.mjs --root /repo --check
for script in test test:tooling lint i18n-check; do
  docker run --rm "$tag-front" npm run "$script"
done
docker run --rm "$tag-front" npm audit --omit=dev --audit-level=high
docker build -t "$tag-browser" browser-executor
docker run --rm "$tag-browser" npm test
docker run --rm "$tag-browser" npm audit --omit=dev --audit-level=high
make tests-focus-gates
make tests-validation-source
make tests-update
