#!/usr/bin/env bash
# Real Git snapshots and release scripts; only scanner/API boundaries are synthetic.
set -euo pipefail
cd "$(dirname "$0")/.."
case_root=$(mktemp -d "${TMPDIR:-/tmp}/galaris-release-check-tests.XXXXXX")
cleanup() {
  status=$?
  if (( status != 0 )) && [[ -f "$case_root/output" ]]; then cat "$case_root/output" >&2; fi
  rm -rf "$case_root"
  exit "$status"
}
trap cleanup EXIT
git clone --quiet --shared --no-checkout "$PWD" "$case_root/repo"
mkdir -p "$case_root/repo/bin" "$case_root/commands" "$case_root/responses"
cp bin/security-check.sh bin/build-release.sh bin/test-upgrade.sh "$case_root/repo/bin/"
if [[ -f bin/check-release.sh ]]; then cp bin/check-release.sh "$case_root/repo/bin/"; fi
export RELEASE_REF
RELEASE_REF=$(git rev-parse HEAD)
export GH_REPO=example/synthetic-release RELEASE_CHECK_TIMEOUT_SECONDS=0
export CALLS="$case_root/calls" RESPONSES="$case_root/responses"
export SNAPSHOT_README="$case_root/scanned-readme" GITHUB_STEP_SUMMARY="$case_root/summary.md"
cat > "$case_root/commands/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\n' "$*" >> "$CALLS"
if [[ ${UPGRADE_CAPTURE:-0} == 1 ]]; then
  source_config=''
  for argument in "$@"; do
    if [[ $argument == */previous-source.yaml ]]; then source_config=$argument; fi
  done
  if [[ " $* " == *' build backend '* && -n "$source_config" ]]; then
    jq -e --arg source "$UPGRADE_EXPECTED_SOURCE" '
      (.services.backend.image | startswith("galaris-upgrade-previous:")) and
      .services.backend.build.context == ($source + "/back") and
      .services.backend.build.additional_contexts.harness_manager == ($source + "/harness_manager") and
      .services.backend.build.additional_contexts.code_executor == ($source + "/code-executor") and
      .services.backend.build.additional_contexts.product_docs == ($source + "/docs") and
      .services.backend.build.additional_contexts.project_docs == ($source + "/project")
    ' "$source_config" >/dev/null
    if [[ ${UPGRADE_BUILD_FAIL:-0} == 1 ]]; then exit 19; fi
    cp "$source_config" "$RESPONSES/previous-built.json"
  fi
  if [[ " $* " == *' /probe.py seed'* && -n ${UPGRADE_EXPECTED_SOURCE:-} ]]; then
    test -f "$RESPONSES/previous-built.json" || { echo 'Historical source has no matching dependency image' >&2; exit 23; }
    test -n "$source_config"
    cmp "$source_config" "$RESPONSES/previous-built.json"
  fi
  exit 0
fi
if [[ " $* " == *' aquasec/trivy:0.74.0 '* ]]; then
  if [[ " $* " == *' image --input '* ]]; then cat "$IMAGE_FINDINGS"; exit 0; fi
  while [[ $1 != -v ]]; do shift; done
  snapshot=${2%:/src:ro}
  test ! -e "$snapshot/.env"
  test ! -e "$snapshot/untracked-secret.txt"
  cp "$snapshot/README.md" "$SNAPSHOT_README"
  exit "${SCANNER_EXIT:-0}"
fi
SH
cat > "$case_root/commands/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'gh %s\n' "$*" >> "$CALLS"
if [[ ${GH_FAIL:-0} == 1 ]]; then echo 'Synthetic API failure' >&2; exit 7; fi
if [[ $* == *quality.yml* ]]; then workflow=quality; else workflow=security; fi
if [[ ${GH_ADVANCE:-0} == 1 && $workflow == security && ! -e "$RESPONSES/advanced" ]]; then
  touch "$RESPONSES/advanced"
  cat "$RESPONSES/security-pending.json"
  exit 0
fi
cat "$RESPONSES/$workflow.json"
SH
cat > "$case_root/commands/sleep" <<'SH'
#!/usr/bin/env bash
printf 'sleep %s\n' "$*" >> "$CALLS"
SH
chmod +x "$case_root/commands/"*
export PATH="$case_root/commands:$PATH"
cd "$case_root/repo"
green() {
  jq -n --arg sha "$RELEASE_REF" --arg repo "$GH_REPO" '[{workflow_runs: [{
    head_sha: $sha, head_repository: {full_name: $repo}, event: "push",
    status: "completed", conclusion: "success", run_number: 10, run_attempt: 1,
    html_url: "https://github.com/example/synthetic-release/actions/runs/100"
  }]}]' > "$RESPONSES/quality.json"
  cp "$RESPONSES/quality.json" "$RESPONSES/security.json"
  : > "$CALLS"
}
blocked() {
  if bash bin/check-release.sh > "$case_root/output" 2>&1; then
    echo 'FAIL: release check accepted invalid evidence' >&2; exit 1
  fi
  if ! grep -qi "${1:-blocked}" "$case_root/output"; then cat "$case_root/output"; exit 1; fi
}
green
printf 'Dirty worktree\n' > README.md
printf 'SYNTHETIC_SECRET=never-copy\n' > .env
printf 'synthetic local data\n' > untracked-secret.txt
bash bin/security-check.sh source "$RELEASE_REF"
git show "$RELEASE_REF:README.md" > "$case_root/expected-readme"
cmp "$case_root/expected-readme" "$SNAPSHOT_README"
grep -q 'semgrep/semgrep:1.176.0' "$CALLS"
echo 'PASS: exact committed snapshot, uncommitted data excluded'

for workflow in quality security; do
  for conclusion in failure cancelled skipped timed_out neutral; do
    green
    jq --arg conclusion "$conclusion" '.[0].workflow_runs[0].conclusion = $conclusion' \
      "$RESPONSES/$workflow.json" > "$case_root/changed"
    mv "$case_root/changed" "$RESPONSES/$workflow.json"
    blocked "$conclusion"
    grep -qi "$workflow" "$case_root/output"
  done
done
echo 'PASS: both required workflows reject every unsuccessful conclusion'

for problem in missing wrong-commit fork pull-request pending newer-failure rerun-failure; do
  green
  case "$problem" in
    missing) filter='.[0].workflow_runs = []' ;;
    wrong-commit) filter='.[0].workflow_runs[0].head_sha = "0000000000000000000000000000000000000000"' ;;
    fork) filter='.[0].workflow_runs[0].head_repository.full_name = "example/untrusted-fork"' ;;
    pull-request) filter='.[0].workflow_runs[0].event = "pull_request"' ;;
    pending) filter='.[0].workflow_runs[0] |= (.status = "in_progress" | .conclusion = null)' ;;
    newer-failure) filter='.[0].workflow_runs += [ (.[0].workflow_runs[0] | .run_number = 11 | .conclusion = "failure") ]' ;;
    rerun-failure) filter='.[0].workflow_runs += [ (.[0].workflow_runs[0] | .run_attempt = 2 | .conclusion = "failure") ]' ;;
  esac
  jq "$filter" "$RESPONSES/security.json" > "$case_root/changed"
  mv "$case_root/changed" "$RESPONSES/security.json"
  blocked security
done
echo 'PASS: missing, stale, fork, PR, pending and superseded successes cannot qualify'

green
SCANNER_EXIT=23 blocked
grep -q 'aquasec/trivy:0.74.0' "$CALLS"
if grep -q 'semgrep/semgrep:1.176.0' "$CALLS"; then exit 1; fi
green
GH_FAIL=1 blocked
echo 'PASS: scanner and API failures block publication'

green
bash bin/check-release.sh > "$case_root/output" 2>&1
grep -q "$RELEASE_REF" "$case_root/output"
grep -q "$RELEASE_REF" "$GITHUB_STEP_SUMMARY"
grep -q 'semgrep/semgrep:1.176.0' "$CALLS"
echo 'PASS: exact-commit CI plus fresh scans qualify and retain a summary'

green
jq '.[0].workflow_runs[0] |= (.status = "in_progress" | .conclusion = null)' \
  "$RESPONSES/security.json" > "$RESPONSES/security-pending.json"
GH_ADVANCE=1 RELEASE_CHECK_TIMEOUT_SECONDS=60 bash bin/check-release.sh > "$case_root/output" 2>&1
grep -q '^sleep ' "$CALLS"
test "$(grep -c 'security.yml' "$CALLS")" -eq 2
echo 'PASS: pending CI is awaited before a fresh scan can qualify'

# Exercise the public API fallback on runners both with and without an installed gh.
mkdir "$case_root/public-commands"
for tool in bash dirname git jq mkdir mktemp tee cat tar rm cp sed grep; do
  ln -s "$(command -v "$tool")" "$case_root/public-commands/$tool"
done
ln -s "$case_root/commands/docker" "$case_root/public-commands/docker"
cat > "$case_root/public-commands/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >> "$CALLS"
if [[ ${GH_FAIL:-0} == 1 ]]; then echo 'Synthetic HTTP failure' >&2; exit 22; fi
if [[ $* == *quality.yml* ]]; then workflow=quality; else workflow=security; fi
for argument in "$@"; do
  if [[ $argument == *'&page='* ]]; then page=${argument##*&page=}; fi
done
jq ".[$((page - 1))]" "$RESPONSES/$workflow.json"
SH
chmod +x "$case_root/public-commands/curl"
green
PATH="$case_root/public-commands" bash bin/check-release.sh > "$case_root/output" 2>&1
grep -q '^curl ' "$CALLS"
GH_FAIL=1 PATH="$case_root/public-commands" blocked
green
jq '[{workflow_runs: [range(0;100) as $n | .[0].workflow_runs[0]]},
     {workflow_runs: [ (.[0].workflow_runs[0] | .run_number = 11 | .conclusion = "failure") ]}]' \
  "$RESPONSES/security.json" > "$case_root/changed"
mv "$case_root/changed" "$RESPONSES/security.json"
PATH="$case_root/public-commands" blocked failure
echo 'PASS: public API checks preserve exact-commit, pagination and failure requirements'

green
if SCANNER_EXIT=23 RELEASE_DIR="$case_root/candidate" bash bin/build-release.sh > "$case_root/output" 2>&1; then exit 1; fi
grep -q 'aquasec/trivy:0.74.0' "$CALLS"
if grep -q 'docker .* build' "$CALLS"; then exit 1; fi
test ! -e "$case_root/candidate"
echo 'PASS: source findings stop bundle creation before image builds'

green
export IMAGE_FINDINGS="$case_root/image-findings.json"
printf '{"Results":[{"Vulnerabilities":[{"VulnerabilityID":"TEST-UNFIXED","Severity":"CRITICAL"}]}]}' > "$IMAGE_FINDINGS"
bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1
grep -q 'WARNING: unfixed CRITICAL' "$case_root/output"
grep -q '"unfixed_critical": 1' "$case_root/output"
jq '.Results[0].Vulnerabilities[0].FixedVersion = "synthetic-fixed-version"' "$IMAGE_FINDINGS" > "$case_root/changed"
mv "$case_root/changed" "$IMAGE_FINDINGS"
if bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1; then exit 1; fi
echo 'PASS: unfixed image criticals are visible and available fixes still block'

# Historical source must use its own complete runtime, including removed dependencies.
historical_source="$case_root/historical source"
mkdir -p "$historical_source/"{back,harness_manager,code-executor,docs,project}
printf '# synthetic historical models\n' > "$historical_source/back/modules.py"
printf 'synthetic-retired-dependency==1.0\n' > "$historical_source/back/pyproject.toml"
green
UPGRADE_CAPTURE=1 UPGRADE_EXPECTED_SOURCE="$historical_source" UPGRADE_SOURCE="$historical_source" \
  bash bin/test-upgrade.sh > "$case_root/output" 2>&1
test "$(grep -c 'docker compose .* build backend' "$CALLS")" -eq 1
test "$(grep -c 'previous-source.yaml.* run .* /probe.py' "$CALLS")" -eq 2
echo 'PASS: historical-source seed and rollback share their own dependency image'

green
if UPGRADE_CAPTURE=1 UPGRADE_EXPECTED_SOURCE="$historical_source" UPGRADE_SOURCE="$historical_source" UPGRADE_BUILD_FAIL=1 \
  bash bin/test-upgrade.sh > "$case_root/output" 2>&1; then exit 1; fi
if grep -q 'up --detach --wait db-test' "$CALLS"; then exit 1; fi
echo 'PASS: historical image build failure stops before creating the test database'

green
immutable_previous="sha256:$(printf '%064d' 1)"
UPGRADE_CAPTURE=1 UPGRADE_PREVIOUS_IMAGE="$immutable_previous" \
  bash bin/test-upgrade.sh > "$case_root/output" 2>&1
if grep -q 'docker compose .* build backend' "$CALLS"; then exit 1; fi
if grep -q "docker image rm $immutable_previous" "$CALLS"; then exit 1; fi
echo 'PASS: supplied immutable previous images are reused and never removed'
