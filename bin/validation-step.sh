#!/usr/bin/env bash
# A step's exit status survives tee and a fresh background shell.
run_with_deadline() {
  local seconds=$1
  shift
  local status=0
  timeout --kill-after=120s "${seconds}s" "$@" || status=$?
  if [[ $status == 124 || $status == 137 ]]; then
    printf 'Validation exceeded its %ss deadline; result is incomplete.\n' "$seconds" >&2
  fi
  return "$status"
}

run_step() {
  set -o pipefail
  local name=$1
  shift
  local gate_started=$SECONDS
  printf '\nRunning %s\n' "$name"
  if (cd "$snapshot" && "$@") 2>&1 | tee "$run_dir/$name.log"; then
    printf 'PASS %s\n' "$name" >> "$report"
  else
    printf 'FAIL %s (see %s.log)\n' "$name" "$name" >> "$report"
    printf 'Duration %s: %ss\n' "$name" "$((SECONDS - gate_started))" >> "$report"
    return 1
  fi
  printf 'Duration %s: %ss\n' "$name" "$((SECONDS - gate_started))" >> "$report"
}
