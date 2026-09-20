#!/usr/bin/env bash
# Qualify one frozen worktree, including uncommitted changes, with isolated services.
set -euo pipefail
cd "$(dirname "$0")/.."
source_root=$PWD
source bin/validation-source.sh
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
printf 'Validation: %s\n' "$run_dir"
failed=0
run_step() {
  local name=$1
  shift
  printf '\nRunning %s\n' "$name"
  if (cd "$snapshot" && "$@") 2>&1 | tee "$run_dir/$name.log"; then
    printf 'PASS %s\n' "$name" >> "$report"
  else
    printf 'FAIL %s (see %s.log)\n' "$name" "$name" >> "$report"
    failed=1
  fi
}
# Never inherit a focused suite or release/deployment configuration from the caller.
unset ARGS TEST_ARGS_BACK COVERAGE_TEST_ARGS RELEASE_DIR GALARIS_FRONT_TEST_SOURCE_DIR
export MAKEFLAGS=
export COVERAGE_DIFF_BASE=${VALIDATION_BASE:-$source_commit}
export COMPOSE_PROJECT_NAME="galaris-validation-$$"
# Report-only Compose runs create a default network even without a database.
# Own that project through teardown, including when a later gate fails.
cleanup() {
  (cd "$snapshot" && docker compose -p "$COMPOSE_PROJECT_NAME" -f compose.test.yaml \
    down --remove-orphans --rmi local) > "$run_dir/cleanup.log" 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
run_step providers make tests-providers
run_step static bash bin/check-static.sh
run_step backend make tests-coverage
run_step components make tests-front-components
run_step mutations make tests-mutations
run_step regressions make regression-check
run_step executor make tests-executor
run_step harness-manager make tests-harness-manager
run_step harness-contracts make tests-harness-contracts
run_step harness-runtimes make tests-harness-runtimes
run_step e2e make tests-e2e ARGS=--repeat-each=3
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
printf 'Exit status: %s\n' "$failed" >> "$report"
cat "$report"
exit "$failed"
