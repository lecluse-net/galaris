#!/usr/bin/env bash
# Build an immutable committed source once; export the exact images for promotion.
set -euo pipefail
cd "$(dirname "$0")/.."
release_ref=$(git rev-parse --verify "${RELEASE_REF:-HEAD}^{commit}")
release_output=$(realpath -m "${RELEASE_DIR:-artifacts/releases/$release_ref}")
if [[ -e "$release_output" ]]; then
  echo "Release destination already exists: $release_output" >&2
  exit 2
fi
release_source=$(mktemp -d "${TMPDIR:-/tmp}/galaris-release.XXXXXX")
trap 'rm -rf "$release_source"' EXIT
git archive "$release_ref" | tar -x -C "$release_source"
mkdir -p "$release_output"
printf '%s\n' "$release_ref" > "$release_output/SOURCE_COMMIT"
printf 'services:\n' > "$release_output/compose.release.yaml"
images=()
RELEASE_BUILD_REF="$release_ref" RELEASE_BUILD_SOURCE="$release_source" \
  docker compose -f "$release_source/compose.release-build.yaml" build
for component in back front browser-executor ssh-executor; do
  tag="galaris-release-$component:$release_ref"
  case "$component" in
    back) service=backend ;;
    front) service=frontend ;;
    ssh-executor) service=ssh-executor ;;
    *) service=browser-executor ;;
  esac
  images+=("$tag")
  printf '  %s:\n    image: %s\n    pull_policy: never\n' "$service" "$tag" >> "$release_output/compose.release.yaml"
  if [[ "$component" == browser-executor ]]; then
    printf '  browser-secrets:\n    image: %s\n    pull_policy: never\n' "$tag" >> "$release_output/compose.release.yaml"
  fi
  image_id=$(docker image inspect --format '{{.Id}}' "$tag")
  printf '%s %s\n' "$image_id" "$tag" >> "$release_output/IMAGE_IDS"
done
if [[ -n "${RELEASE_HARNESS_IMAGES_FILE:-}" ]]; then
  cp "$RELEASE_HARNESS_IMAGES_FILE" "$release_output/MANAGED_HARNESSES"
  while read -r expected_id image_tag; do
    test "$(docker image inspect --format '{{.Id}}' "$image_tag")" = "$expected_id"
    images+=("$image_tag")
    printf '%s %s\n' "$expected_id" "$image_tag" >> "$release_output/IMAGE_IDS"
  done < "$release_output/MANAGED_HARNESSES"
else
  printf '%s\n' '# Managed agent harnesses are external to this bundle. Their deployment requires its own tested image manifest.' > "$release_output/MANAGED_HARNESSES"
fi
# A production import catches accidental dependence on dev-only packages.
docker run --rm --network none --entrypoint python \
  -e APP_ENV=test -e AUTH_SECRET_KEY=release-smoke-auth-secret-000000001 \
  -e BROWSER_EXECUTOR_TOKEN=release-smoke-browser-token-000001 \
  -e ENCRYPTION_MASTER_KEY=release-smoke-encryption-key-00001 \
  "galaris-release-back:$release_ref" -c 'import importlib.util; import main; assert importlib.util.find_spec("pytest") is None'
# Never regenerate after freezing sources: reject stale maps or incomplete packaged docs.
docker run --rm --network none --entrypoint python \
  -e ENCRYPTION_MASTER_KEY=documentation-offline-check-key-0001 "galaris-release-back:$release_ref" \
  -m app.documentation check
docker run --rm --network none --entrypoint python -v "$release_source:/repo:ro" \
  "galaris-release-back:$release_ref" /repo/back/scripts/project_context.py --root /repo --check
GALARIS_FRONT_TEST_SOURCE_DIR="$release_source/front" \
  docker compose -p galaris-release-context -f "$release_source/compose.front-tests.yaml" run --build --rm --no-deps -T \
  -v /app/node_modules -v "$release_source:/repo:ro" frontend \
  node scripts/navigation-context.mjs --root /repo --check
docker save "${images[@]}" | gzip > "$release_output/images.tar.gz"
(
  cd "$release_output"
  sha256sum SOURCE_COMMIT IMAGE_IDS compose.release.yaml images.tar.gz MANAGED_HARNESSES > SHA256SUMS
)
echo "Release built from $release_ref in $release_output. Verify and test this bundle before promotion."
