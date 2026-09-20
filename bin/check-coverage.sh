#!/usr/bin/env bash
# Git runs on the checkout host; Python remains in the isolated test image.
set -euo pipefail
cd "$(dirname "$0")/.."
arguments=()
if [[ -n "${COVERAGE_DIFF_BASE:-}" ]]; then
  base_commit=$(git rev-parse --verify "${COVERAGE_DIFF_BASE}^{commit}")
  mkdir -p artifacts
  comparison_dir=$(mktemp -d "$PWD/artifacts/coverage-diff.XXXXXX")
  trap 'rm -rf "$comparison_dir"' EXIT
  git diff --no-ext-diff --unified=0 "$base_commit" -- back > "$comparison_dir/changes.patch"
  # git diff alone omits new, untracked files in a local validation snapshot.
  while IFS= read -r -d '' source_file; do
    result=0
    git diff --no-ext-diff --no-index --unified=0 -- /dev/null "$source_file" >> "$comparison_dir/changes.patch" || result=$?
    if [[ "$result" -gt 1 ]]; then exit "$result"; fi
  done < <(git ls-files --others --exclude-standard -z -- back)
  relative_dir=${comparison_dir#"$PWD/"}
  arguments=(--base "$base_commit" --diff "/repo/$relative_dir/changes.patch")
fi
docker compose -f compose.test.yaml run --rm --no-deps backend \
  python scripts/check_critical_coverage.py "${arguments[@]}"
docker compose -f compose.test.yaml run --rm --no-deps backend \
  python scripts/check_critical_coverage.py --xml /repo/artifacts/coverage-full.xml \
  --config coverage-all-domains.json --report /repo/artifacts/coverage-all-floors.json
