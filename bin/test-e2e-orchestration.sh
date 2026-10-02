#!/usr/bin/env bash
# Exercise the actual stack coordinator; Docker is the external boundary.
set -euo pipefail
cd "$(dirname "$0")/.."
source bin/validation-step.sh
case_dir=$(mktemp -d)
coordinator=
cleanup() {
  if [[ -n $coordinator ]]; then
    kill -TERM -- "-$coordinator" 2>/dev/null || true
    wait "$coordinator" 2>/dev/null || true
  fi
  rm -rf "$case_dir"
}
trap cleanup EXIT
mkdir -p "$case_dir/bin"
# A hung command must stop and retain a failing, incomplete result.
deadline_status=0
run_with_deadline 1 bash -c 'sleep 30' > "$case_dir/deadline.log" 2>&1 || deadline_status=$?
test "$deadline_status" == 124
rg -q 'result is incomplete' "$case_dir/deadline.log"
# A command failing before tee must fail even in a fresh non-strict shell.
snapshot=$PWD
run_dir="$case_dir/steps"
report="$run_dir/summary.txt"
mkdir -p "$run_dir"
export snapshot run_dir report
export -f run_step
bash -c 'run_step success bash -c "echo verified"' > "$case_dir/step-success.log"
if bash -c 'run_step failure bash -c "echo rejected; exit 7"' > "$case_dir/step-failure.log"; then
  echo 'FAIL: tee must not hide a failed validation gate' >&2
  exit 1
fi
rg -q '^PASS success$' "$report"
rg -q '^FAIL failure ' "$report"
test "$(cat "$run_dir/failure.log")" == rejected
cat > "$case_dir/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
project=
for ((index=1; index <= $#; index++)); do
  if [[ ${!index} == -p ]]; then
    ((index+=1))
    project=${!index}
  fi
done
case " $* " in
  *' run '*)
    mkdir -p "$E2E_PROOF_DIR/started"
    touch "$E2E_PROOF_DIR/started/$project"
    # A serial implementation cannot reach this barrier.
    for ((attempt=0; attempt < 100; attempt++)); do
      count=$(rg --files "$E2E_PROOF_DIR/started" | wc -l)
      if [[ $count == 3 ]]; then break; fi
      sleep 0.05
    done
    test "$count" == 3
    if [[ ${E2E_PROOF_BLOCK:-0} == 1 ]]; then
      while true; do sleep 1; done
    fi
    if [[ ${E2E_PROOF_FAIL:-} == firefox && " $* " == *' --project=firefox '* ]]; then
      exit 7
    fi
    ;;
  *' down '*)
    mkdir -p "$E2E_PROOF_DIR/stopped"
    touch "$E2E_PROOF_DIR/stopped/$project"
    ;;
esac
MOCK
chmod +x "$case_dir/bin/docker"
export PATH="$case_dir/bin:$PATH"
export E2E_PROOF_DIR="$case_dir/success"
bash bin/test-e2e.sh > "$case_dir/success.log" 2>&1
test "$(rg -c '^PASS ' "$case_dir/success.log")" == 3
test "$(rg --files "$E2E_PROOF_DIR/stopped" | wc -l)" == 3
export E2E_PROOF_DIR="$case_dir/failure"
if E2E_PROOF_FAIL=firefox bash bin/test-e2e.sh > "$case_dir/failure.log" 2>&1; then
  echo 'FAIL: a failed browser must fail the group' >&2
  exit 1
fi
test "$(rg -c '^PASS ' "$case_dir/failure.log")" == 2
test "$(rg --files "$E2E_PROOF_DIR/stopped" | wc -l)" == 3
export E2E_PROOF_DIR="$case_dir/cancellation"
E2E_PROOF_BLOCK=1 setsid bash bin/test-e2e.sh > "$case_dir/cancellation.log" 2>&1 &
coordinator=$!
for ((attempt=0; attempt < 100; attempt++)); do
  count=$(rg --files "$E2E_PROOF_DIR/started" 2>/dev/null | wc -l || true)
  if [[ $count == 3 ]]; then break; fi
  sleep 0.05
done
kill -TERM -- "-$coordinator"
if wait "$coordinator"; then
  echo 'FAIL: cancellation must fail the group' >&2
  exit 1
fi
coordinator=
test "$count" == 3
test "$(rg --files "$E2E_PROOF_DIR/stopped" | wc -l)" == 3
echo 'PASS: tee preserves failures, concurrent isolated stacks and cancellation cleanup'
