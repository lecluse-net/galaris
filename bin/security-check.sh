#!/usr/bin/env bash
# Reproducible local/CI scans; ignored files and live data never enter the scanner.
set -euo pipefail
cd "$(dirname "$0")/.."
scan_root=$(mktemp -d "${TMPDIR:-/tmp}/galaris-security.XXXXXX")
trap 'rm -rf "$scan_root"' EXIT
mkdir -p "$scan_root/source"
git ls-files -z --cached --others --exclude-standard -- . ':!:refs' |
  while IFS= read -r -d '' entry; do
    if [[ -f "$entry" && ! -L "$entry" ]]; then printf '%s\0' "$entry"; fi
  done |
  tar --null -T - -cf - |
  tar -xf - -C "$scan_root/source"

trivy=(docker run --rm -v "$scan_root/source:/src:ro" -w /src aquasec/trivy:0.74.0)
if [[ ${1:-} == image ]]; then
  [[ $# == 2 ]] || { echo "Usage: $0 image IMAGE" >&2; exit 2; }
  docker save "$2" -o "$scan_root/source/image.tar"
  mkdir -p artifacts/security
  report="artifacts/security/$(printf '%s' "$2" | tr '/:' '--').json"
  "${trivy[@]}" image --input /src/image.tar --scanners vuln \
    --severity HIGH,CRITICAL --ignorefile /src/security/trivy-ignore.yaml --format json > "$report"
  # Keep the complete inventory, including unfixed OS advisories. A green gate
  # means no available HIGH/CRITICAL fix was left unapplied, not no known CVEs.
  jq '[.Results[]?.Vulnerabilities[]?] | {
    total: length,
    fix_available: map(select(.FixedVersion != null and .FixedVersion != "")) | length
  }' "$report"
  jq -e 'all(.Results[]?.Vulnerabilities[]?;
    .FixedVersion == null or .FixedVersion == "")' "$report" >/dev/null
else
  "${trivy[@]}" fs --scanners vuln,secret --severity HIGH,CRITICAL \
    --ignorefile security/trivy-ignore.yaml --exit-code 1 --skip-dirs refs .
  docker run --rm -v "$scan_root/source:/src:ro" -w /src semgrep/semgrep:1.176.0 \
    semgrep scan --config p/python --config p/javascript --config p/typescript \
    --severity ERROR --exclude '**/tests/**' --exclude '**/conftest.py' \
    --exclude '**/*.test.*' --exclude '.agents' --exclude '.codex' \
    --metrics off --error
fi
