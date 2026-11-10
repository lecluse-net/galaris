#!/usr/bin/env bash
# Run in the development container and retain diagnostic evidence under artifacts/.
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose)
while [[ $# -gt 0 && "$1" != -- ]]; do compose+=("$1"); shift; done
[[ "${1:-}" == -- ]] && shift
output=${BENCHMARK_EVIDENCE_DIR:-$(mktemp -d artifacts/operating-benchmark.XXXXXX)}
case "$output" in artifacts/operating-benchmark.*) ;; *) printf 'Use an artifacts/operating-benchmark.* evidence directory\n' >&2; exit 2 ;; esac
container_output="/tmp/$(basename "$output")"
status=0
"${compose[@]}" exec -T backend python scripts/benchmark_operating_knowledge.py \
  --output "$container_output" "$@" > >(tee -a "$output/run.log") 2>&1 || status=$?
# Copy even after an interrupted or failed campaign. Preserve the original failure.
if ! "${compose[@]}" cp "backend:$container_output/." "$output/"; then
  printf 'Could not export all benchmark evidence to %s\n' "$output" >&2
  [[ "$status" != 0 ]] || status=1
fi
printf 'Benchmark evidence: %s\n' "$output"
exit "$status"
