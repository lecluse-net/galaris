#!/usr/bin/env bash
# Real Git snapshots and release scripts; only scanner/API boundaries are synthetic.
set -euo pipefail
cd "$(dirname "$0")/.."
release_test_source=$PWD
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
if [[ " $* " == *' aquasec/trivy:0.76.1 '* ]]; then
  if [[ " $* " == *' image --input '* ]]; then
    if [[ " $* " == *' --vex '* ]]; then cat "$IMAGE_ASSESSMENT"; else cat "$IMAGE_FINDINGS"; fi
    exit 0
  fi
  while [[ $1 != -v ]]; do shift; done
  snapshot=${2%:/src:ro}
  test ! -e "$snapshot/.env"
  test ! -e "$snapshot/untracked-secret.txt"
  cp "$snapshot/README.md" "$SNAPSHOT_README"
  exit "${SCANNER_EXIT:-0}"
fi
if [[ " $* " == *' /verify.py '* ]]; then
  printf '{"package":"linux-libc-dev","verified_headers":1,"kernel_payload_present":false}\n'
  exit "${HEADER_PROOF_EXIT:-0}"
fi
if [[ " $* " == *' semgrep/semgrep:1.176.0 '* ]]; then exit "${SAST_EXIT:-0}"; fi
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

for conclusion in failure cancelled skipped timed_out neutral; do
    green
    jq --arg conclusion "$conclusion" '.[0].workflow_runs[0].conclusion = $conclusion' \
      "$RESPONSES/security.json" > "$case_root/changed"
    mv "$case_root/changed" "$RESPONSES/security.json"
    blocked "$conclusion"
    grep -qi security "$case_root/output"
done
echo 'PASS: security rejects every unsuccessful conclusion'

for quality_state in failure cancelled skipped timed_out pending missing; do
  green
  if [[ $quality_state == missing ]]; then
    rm "$RESPONSES/quality.json"
  else
    jq --arg state "$quality_state" '.[0].workflow_runs[0] |=
      (if $state == "pending" then .status = "in_progress" | .conclusion = null
       else .conclusion = $state end)' "$RESPONSES/quality.json" > "$case_root/changed"
    mv "$case_root/changed" "$RESPONSES/quality.json"
  fi
  bash bin/check-release.sh > "$case_root/output" 2>&1
  if grep -q 'quality.yml' "$CALLS"; then echo 'Quality must not gate publication' >&2; exit 1; fi
done
echo 'PASS: failed, cancelled, pending and absent functional CI does not gate publication'

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
grep -q 'aquasec/trivy:0.76.1' "$CALLS"
if grep -q 'semgrep/semgrep:1.176.0' "$CALLS"; then exit 1; fi
green
GH_FAIL=1 blocked
green
SAST_EXIT=17 blocked
echo 'PASS: scanner and API failures block publication'

green
bash bin/check-release.sh > "$case_root/output" 2>&1
grep -q "$RELEASE_REF" "$case_root/output"
grep -q "$RELEASE_REF" "$GITHUB_STEP_SUMMARY"
grep -q 'semgrep/semgrep:1.176.0' "$CALLS"
echo 'PASS: exact-commit security CI plus fresh scans qualify and retain a summary'

# Execute the actual folded Quality result gate with synthetic job outcomes.
quality_gate=$(awk '
  /^  required:/ { required = 1 }
  required && /run: >-/ { script = 1; next }
  script && /^          / { printf "%s ", substr($0, 11); next }
  script { exit }
' "$release_test_source/.github/workflows/quality.yml")
test -n "$quality_gate"
quality_results=$(jq -n '{static:{result:"success"}, "dependency-review":{result:"skipped"}} +
  (["providers","backend-tests","frontend-components","chat-e2e","restore"] |
    map({key:.,value:{result:"skipped"}}) | from_entries)')
FULL=false EVENT=push RESULTS="$quality_results" bash -euc "$quality_gate" > "$case_root/output" 2>&1
if FULL=true EVENT=workflow_dispatch RESULTS="$quality_results" bash -euc "$quality_gate" > "$case_root/output" 2>&1; then exit 1; fi
if FULL=false EVENT=pull_request RESULTS="$quality_results" bash -euc "$quality_gate" > "$case_root/output" 2>&1; then exit 1; fi
quality_failed=$(jq '.static.result = "failure"' <<< "$quality_results")
if FULL=false EVENT=push RESULTS="$quality_failed" bash -euc "$quality_gate" > "$case_root/output" 2>&1; then exit 1; fi
quality_skipped=$(jq '.static.result = "skipped"' <<< "$quality_results")
if FULL=false EVENT=push RESULTS="$quality_skipped" bash -euc "$quality_gate" > "$case_root/output" 2>&1; then exit 1; fi
quality_unknown=$(jq '.unexpected = {result:"skipped"}' <<< "$quality_results")
if FULL=false EVENT=push RESULTS="$quality_unknown" bash -euc "$quality_gate" > "$case_root/output" 2>&1; then exit 1; fi
quality_full=$(jq 'with_entries(.value.result = "success")' <<< "$quality_results")
FULL=true EVENT=workflow_dispatch RESULTS="$quality_full" bash -euc "$quality_gate" > "$case_root/output" 2>&1
quality_failed=$(jq '."chat-e2e".result = "failure"' <<< "$quality_full")
if FULL=true EVENT=workflow_dispatch RESULTS="$quality_failed" bash -euc "$quality_gate" > "$case_root/output" 2>&1; then exit 1; fi
echo 'PASS: quick Quality permits only omitted full suites; requested full suites and static failures stay honest'

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
grep -q 'aquasec/trivy:0.76.1' "$CALLS"
if grep -q 'docker .* build' "$CALLS"; then exit 1; fi
test ! -e "$case_root/candidate"
echo 'PASS: source findings stop bundle creation before image builds'

green
export IMAGE_FINDINGS="$case_root/image-findings.json"
for severity in HIGH CRITICAL; do
  for fixed in false true; do
    jq -n --arg severity "$severity" --argjson fixed "$fixed" '{Results:[{Vulnerabilities:[
      ({VulnerabilityID:"TEST-DANGEROUS",Severity:$severity} +
       if $fixed then {FixedVersion:"synthetic-fixed-version"} else {} end)
    ]}]}' > "$IMAGE_FINDINGS"
    if bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1; then exit 1; fi
    grep -q '"total": 1' "$case_root/output"
  done
done
printf '{"Results":[]}' > "$IMAGE_FINDINGS"
bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1
printf '{}' > "$IMAGE_FINDINGS"
if bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1; then exit 1; fi
echo 'PASS: dangerous image findings block with or without a fix; missing inventories cannot qualify'

# VEX may classify only reviewed CVE/package/version tuples after artifact proof.
mkdir -p security
export IMAGE_ASSESSMENT="$case_root/image-assessment.json"
reviewed_purl='pkg:deb/ubuntu/linux-libc-dev@0.0.synthetic?arch=amd64&distro=ubuntu-26.04'
jq -n --arg purl "$reviewed_purl" '{x_galaris_review_expires:"2999-01-01",statements:[{
  vulnerability:{name:"TEST-REVIEWED-HEADER"}, products:[{"@id":$purl}]}]}' > security/ssh-kernel-headers.openvex.json
jq -n --arg purl "$reviewed_purl" '{Metadata:{OS:{Family:"ubuntu",Name:"26.04"},
  ImageID:("sha256:" + ("a" * 64)),ImageConfig:{config:{Labels:{"org.opencontainers.image.title":"galaris-ssh-executor"}}}},
  Results:[{Vulnerabilities:[{VulnerabilityID:"TEST-REVIEWED-HEADER",Severity:"CRITICAL",PkgName:"linux-libc-dev",
    InstalledVersion:"0.0.synthetic",PkgIdentifier:{PURL:$purl}}]}]}' > "$IMAGE_FINDINGS"
jq '.Results |= map(.ExperimentalModifiedFindings = [.Vulnerabilities[] | {Finding:.,Status:"not_affected",Statement:"vulnerable_code_not_present"}] | .Vulnerabilities=[])' \
  "$IMAGE_FINDINGS" > "$IMAGE_ASSESSMENT"
bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1
grep -q 'TEST-REVIEWED-HEADER' "$case_root/output"
grep -q 'vulnerable_code_not_present' "$case_root/output"
if HEADER_PROOF_EXIT=19 bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1; then exit 1; fi
cp "$IMAGE_ASSESSMENT" "$case_root/valid-assessment"
printf '{"Results":[]}' > "$IMAGE_ASSESSMENT"
if bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1; then exit 1; fi
cp "$case_root/valid-assessment" "$IMAGE_ASSESSMENT"
cp "$IMAGE_FINDINGS" "$case_root/reviewed-header"
for change in '.Results[0].Vulnerabilities[0].VulnerabilityID="TEST-UNREVIEWED"' \
  '.Results[0].Vulnerabilities[0].PkgIdentifier.PURL="pkg:deb/ubuntu/linux-libc-dev@different"' \
  '.Metadata.ImageConfig.config.Labels["org.opencontainers.image.title"]="other-image"'; do
  jq "$change" "$case_root/reviewed-header" > "$IMAGE_FINDINGS"
  if bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1; then exit 1; fi
done
cp "$case_root/reviewed-header" "$IMAGE_FINDINGS"
jq '.x_galaris_review_expires="2000-01-01"' security/ssh-kernel-headers.openvex.json > "$case_root/expired-vex"
mv "$case_root/expired-vex" security/ssh-kernel-headers.openvex.json
if bash bin/security-check.sh image synthetic-image > "$case_root/output" 2>&1; then exit 1; fi
grep -q 'review expired' "$case_root/output"
echo 'PASS: scoped VEX retains every raw finding; failed proof, wrong image/version/CVE, expiry and missing assessment block'

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
