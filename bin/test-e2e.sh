#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Keep mutable provider settings, PWA volumes and database rows separate across
# browsers. Tests remain sequential inside each browser's own Compose project.
single_project=false
for argument in "$@"; do
  case "$argument" in
    --project|--project=*|--list|--help|--version) single_project=true ;;
  esac
done
if ! "$single_project"; then
  group_dir="$PWD/artifacts/e2e/galaris-e2e-group-$$"
  mkdir -p "$group_dir"
  children=()
  cleanup_group() {
    for child in "${children[@]}"; do
      kill -TERM -- "-$child" 2>/dev/null || true
    done
    for child in "${children[@]}"; do wait "$child" 2>/dev/null || true; done
  }
  trap cleanup_group EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  browsers=(chromium firefox webkit)
  for browser in "${browsers[@]}"; do
    printf 'Running %s in an isolated stack (log: %s/%s.log)\n' "$browser" "$group_dir" "$browser"
    setsid bash bin/test-e2e.sh "--project=$browser" "$@" > "$group_dir/$browser.log" 2>&1 &
    children+=("$!")
  done
  failed=0
  for index in "${!children[@]}"; do
    if wait "${children[$index]}"; then
      printf 'PASS %s\n' "${browsers[$index]}"
    else
      printf 'FAIL %s (see %s/%s.log)\n' "${browsers[$index]}" "$group_dir" "${browsers[$index]}"
      failed=1
    fi
    unset 'children[index]'
  done
  children=()
  exit "$failed"
fi
# A unique project also permits concurrent CI jobs without stopping each other.
project="galaris-e2e-${GITHUB_RUN_ID:-local}-$$"
export GALARIS_E2E_ARTIFACT_DIR="$(pwd)/artifacts/e2e/$project"
compose=(docker compose -p "$project" -f compose.e2e.yaml)
release_mode=false
if [[ -n "${RELEASE_DIR:-}" ]]; then
  release_directory=$(realpath "$RELEASE_DIR")
  (cd "$release_directory" && sha256sum --check SHA256SUMS)
  while read -r expected_id image_tag; do
    test "$(docker image inspect --format '{{.Id}}' "$image_tag")" = "$expected_id"
    case "$image_tag" in
      galaris-release-back:*) export GALARIS_RELEASE_BACKEND_IMAGE="$expected_id" ;;
      galaris-release-front:*) export GALARIS_RELEASE_FRONTEND_IMAGE="$expected_id" ;;
    esac
  done < "$release_directory/IMAGE_IDS"
  compose+=(-f compose.release-e2e.yaml)
  release_mode=true
fi
mkdir -p "$GALARIS_E2E_ARTIFACT_DIR"
cleanup() {
  "${compose[@]}" logs --no-color backend frontend > "$GALARIS_E2E_ARTIFACT_DIR/services.log" 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans --rmi local >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if "$release_mode"; then
  "${compose[@]}" build runner browser-executor
  "${compose[@]}" up -d --no-build --pull never --wait frontend
  for service in backend frontend; do
    container=$("${compose[@]}" ps -q "$service")
    case "$service" in
      backend) expected="$GALARIS_RELEASE_BACKEND_IMAGE" ;;
      frontend) expected="$GALARIS_RELEASE_FRONTEND_IMAGE" ;;
    esac
    test "$(docker inspect --format '{{.Image}}' "$container")" = "$expected"
  done
else
  "${compose[@]}" build
  "${compose[@]}" up -d --wait frontend
fi
# The exact running backend must contain readable, searchable FR/EN documentation.
"${compose[@]}" exec -T backend python -m app.documentation refresh
# WebKit uses its GTK port; Xvfb supplies a display inside the isolated runner.
"${compose[@]}" run --rm --no-deps runner xvfb-run -a npm test -- "$@"
