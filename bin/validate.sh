#!/usr/bin/env bash
# Qualify one frozen worktree, including uncommitted changes, with isolated services.
set -euo pipefail
validation_limit=${VALIDATION_TIMEOUT_SECONDS:-2700}
validation_repeats=${VALIDATION_E2E_REPEATS:-1}
for value in "$validation_limit" "$validation_repeats"; do
  if [[ ! $value =~ ^[1-9][0-9]*$ ]]; then
    printf 'Validation timeout and repetition count must be positive integers.\n' >&2
    exit 2
  fi
done
if [[ ${1:-} != --timed-run ]]; then
  source "$(dirname "$0")/validation-step.sh"
  run_with_deadline "$validation_limit" bash "$0" --timed-run "$@"
  exit $?
fi
shift
# Parse the entire coordinator before waiting on long-running gates. Editing
# the worktree during validation must produce STALE, not corrupt Bash's reader.
main() {
cd "$(dirname "$0")/.."
source_root=$PWD
validation_started=$SECONDS
source bin/validation-source.sh
source bin/validation-step.sh
run_dir=$(mktemp -d "$source_root/artifacts-validation.XXXXXX")
# Move under the ignored artifact tree before enumerating untracked source files.
mkdir -p artifacts/validation
destination="$source_root/artifacts/validation/$(basename "$run_dir")"
mv "$run_dir" "$destination"
run_dir=$destination
snapshot="$run_dir/source"
validation_archive "$source_root" "$run_dir/source.tar"
source_hash=$(sha256sum "$run_dir/source.tar" | cut -d ' ' -f1)
source_commit=$(git rev-parse HEAD)
git clone --quiet --shared --no-checkout "$source_root" "$snapshot"
git -C "$snapshot" read-tree HEAD
tar -C "$snapshot" -xf "$run_dir/source.tar"
# Refuse an inconsistent copy if another editor changed the source during capture.
validation_archive "$source_root" "$run_dir/after.tar"
cmp "$run_dir/source.tar" "$run_dir/after.tar"
rm "$run_dir/after.tar"
cp "$snapshot/.env.example" "$snapshot/.env"
sed -i 's/^#\?APP_ENV=prod$/APP_ENV=test/' "$snapshot/.env"
(cd "$snapshot" && bash bin/update-secrets.sh) > "$run_dir/configuration.log" 2>&1
mkdir -p "$snapshot/artifacts"
report="$run_dir/summary.txt"
printf 'Source commit: %s\nSource SHA256: %s\nSnapshot: %s\n' "$source_commit" "$source_hash" "$snapshot" > "$report"
printf 'E2E repetitions per browser: %s\nDeadline: %ss\n' "$validation_repeats" "$validation_limit" >> "$report"
printf 'Validation: %s\n' "$run_dir"
failed=0
# Never inherit a focused suite or release/deployment configuration from the caller.
unset ARGS TEST_ARGS_BACK COVERAGE_TEST_ARGS RELEASE_DIR GALARIS_FRONT_TEST_SOURCE_DIR
export MAKEFLAGS=
export COVERAGE_DIFF_BASE=${VALIDATION_BASE:-$source_commit}
export COMPOSE_PROJECT_NAME="galaris-validation-$$"
# Report-only Compose runs create a default network even without a database.
# Own that project through teardown, including when a later gate fails.
parallel_children=()
cleanup() {
  for child in "${parallel_children[@]}"; do
    kill -TERM -- "-$child" 2>/dev/null || true
  done
  for child in "${parallel_children[@]}"; do wait "$child" 2>/dev/null || true; done
  (cd "$snapshot" && docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.test.yaml \
    down --remove-orphans --rmi local) > "$run_dir/cleanup.log" 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
run_step providers make tests-providers || failed=1
run_step static bash bin/check-static.sh || failed=1
# These gates own independent databases, Compose projects and artifact trees.
# Keep their logs and propagate every exit status, even when another gate fails.
export snapshot run_dir report
export -f run_step
for gate in backend components e2e mutations; do
  case "$gate" in
    backend) command=(make tests-coverage) ;;
    components) command=(make tests-front-components) ;;
    e2e) command=(make tests-e2e "ARGS=--repeat-each=$validation_repeats") ;;
    mutations) command=(make tests-mutations) ;;
  esac
  setsid bash -euo pipefail -c 'run_step "$@"' bash "$gate" "${command[@]}" &
  parallel_children+=("$!")
done
for index in "${!parallel_children[@]}"; do
  wait "${parallel_children[$index]}" || failed=1
  unset 'parallel_children[index]'
done
parallel_children=()
run_step regressions make regression-check || failed=1
run_step executor make tests-executor || failed=1
run_step harness-manager make tests-harness-manager || failed=1
run_step harness-contracts make tests-harness-contracts || failed=1
run_step harness-runtimes make tests-harness-runtimes || failed=1
validation_archive "$snapshot" "$run_dir/tested-after.tar"
if ! cmp -s "$run_dir/source.tar" "$run_dir/tested-after.tar"; then
  printf 'MUTATED Tests or generation changed the snapshot sources; inspect source before accepting results.\n' >> "$report"
  failed=1
fi
rm "$run_dir/tested-after.tar"
validation_archive "$source_root" "$run_dir/after.tar"
if ! cmp -s "$run_dir/source.tar" "$run_dir/after.tar" || [[ $(git -C "$source_root" rev-parse HEAD) != "$source_commit" ]]; then
  printf 'STALE Source changed during validation; results apply only to the recorded snapshot. Rerun make validate.\n' >> "$report"
  failed=1
fi
rm "$run_dir/after.tar"
printf 'Duration total: %ss\n' "$((SECONDS - validation_started))" >> "$report"
printf 'Exit status: %s\n' "$failed" >> "$report"
cat "$report"
exit "$failed"
}
main "$@"
