#!/usr/bin/env bash
# Real Git snapshots and Python reporter; only the external scanner is replaced.
set -euo pipefail
cd "$(dirname "$0")/.."
case_root=$(mktemp -d "${TMPDIR:-/tmp}/galaris-dependency-audit-test.XXXXXX")
cleanup() {
  status=$?
  if (( status != 0 )) && [[ -f "$case_root/output.log" ]]; then cat "$case_root/output.log" >&2; fi
  rm -rf -- "$case_root"
  exit "$status"
}
trap cleanup EXIT
export AUDIT_REAL_DOCKER
AUDIT_REAL_DOCKER=$(command -v docker)
mkdir -p "$case_root/repo/bin" "$case_root/repo/tooling" "$case_root/commands" "$case_root/outside"
cp bin/dependencies-audit.sh "$case_root/repo/bin/"
cp -R tooling/dependencies "$case_root/repo/tooling/"
printf 'Synthetic external secret\n' > "$case_root/outside/secret.txt"
cat > "$case_root/commands/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ " $* " == *' aquasec/trivy:0.76.1 '* ]]; then
  snapshot=''; output=''
  for argument in "$@"; do
    case "$argument" in
      *:/snapshot:ro) snapshot=${argument%:/snapshot:ro} ;;
      *:/report) output=${argument%:/report} ;;
    esac
  done
  test -n "$snapshot" && test -n "$output"
  test "$(cat "$snapshot/repo/README.md")" == visible-uncommitted
  test -f "$snapshot/repo/front/package.json"
  test ! -e "$snapshot/repo/.env"
  test ! -e "$snapshot/repo/node_modules"
  test ! -e "$snapshot/repo/artifacts"
  test ! -e "$snapshot/repo/external-link"
  test ! -e "$snapshot/repo/directory-link"
  printf '{"Results":[]}\n' > "$output/source.trivy.json"
  echo 'Synthetic scanner evidence retained' >&2
  exit "${AUDIT_SCANNER_EXIT:-0}"
fi
if [[ ${1:-} == run ]]; then
  if [[ " $* " == *' --network none '* ]]; then exec "$AUDIT_REAL_DOCKER" "$@"; fi
  shift
  # The fixture has no registry dependencies, so every helper is network-free.
  exec "$AUDIT_REAL_DOCKER" run --network none "$@"
fi
exec "$AUDIT_REAL_DOCKER" "$@"
SH
chmod +x "$case_root/commands/docker"
cd "$case_root/repo"
git init -q
printf '.env\n/node_modules/\n/artifacts/\n/tooling/\n' > .gitignore
printf 'visible-index\n' > README.md
git add .gitignore README.md bin
printf 'visible-uncommitted\n' > README.md
printf 'Synthetic ignored credential\n' > .env
mkdir -p front node_modules/synthetic
printf '{"private":true,"scripts":{"postinstall":"touch script-ran"}}\n' > front/package.json
printf 'Synthetic ignored dependency\n' > node_modules/synthetic/secret.txt
ln -s "$case_root/outside/secret.txt" external-link
ln -s "$case_root/outside" directory-link
before=$(sha256sum README.md front/package.json .env)
export PATH="$case_root/commands:$PATH" IMAGES='' FAIL_ON=HIGH ALL_VERSIONS=0
export REFRESH_VERSIONS=0
# Synthetic, fresh registry response for the scanner reference in the wrapper.
# Keep this boundary offline while exercising the actual reporter and cache.
mkdir -p artifacts/dependencies/.cache
jq -n --argjson timestamp "$(date +%s)" \
  '{"[\"docker\", \"aquasec/trivy:0.76.1\"]":{fetched_at:$timestamp,
    value:{latest_digest:"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      url:"https://example.test/synthetic-scanner"}}}' > artifacts/dependencies/.cache/versions.json
bash bin/dependencies-audit.sh > "$case_root/output.log" 2>&1
report=$(ls -td artifacts/dependencies/audit-* | head -1)
jq -e '.summary.exit_code == 0 and .summary.errors == 0' "$report/report.json" >/dev/null
test ! -e script-ran
test "$before" == "$(sha256sum README.md front/package.json .env)"
echo 'PASS: Git-visible changes are scanned; ignored data and symlinks stay outside; no source/package mutation'
status=0
AUDIT_SCANNER_EXIT=19 bash bin/dependencies-audit.sh > "$case_root/output.log" 2>&1 || status=$?
test "$status" -eq 2
report=$(ls -td artifacts/dependencies/audit-* | head -1)
jq -e '.summary.exit_code == 2 and any(.errors[]; contains("exit 19"))' "$report/report.json" >/dev/null
test -s "$report/source.log"
test -s "$report/summary.md"
echo 'PASS: scanner failure retains its logs and an incomplete report'
