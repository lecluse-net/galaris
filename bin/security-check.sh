#!/usr/bin/env bash
# Reproducible local/CI scans; ignored files and live data never enter the scanner.
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  '') [[ $# == 0 ]] ;;
  image|source) [[ $# == 2 ]] ;;
  *) echo "Usage: $0 [source COMMIT | image IMAGE]" >&2; exit 2 ;;
esac
scan_root=$(mktemp -d "${TMPDIR:-/tmp}/galaris-security.XXXXXX")
trap 'rm -rf "$scan_root"' EXIT
mkdir -p "$scan_root/source"
if [[ ${1:-} == source ]]; then
  source_commit=$(git rev-parse --verify --end-of-options "$2^{commit}")
  echo "Scanning committed source: $source_commit"
  git archive "$source_commit" | tar -xf - -C "$scan_root/source"
else
  git ls-files -z --cached --others --exclude-standard -- . ':!:refs' |
    while IFS= read -r -d '' entry; do
      if [[ -f "$entry" && ! -L "$entry" ]]; then printf '%s\0' "$entry"; fi
    done |
    tar --null -T - -cf - |
    tar -xf - -C "$scan_root/source"
fi

trivy=(docker run --rm -v "$scan_root/source:/src:ro" -w /src aquasec/trivy:0.74.0)
if [[ ${1:-} == image ]]; then
  [[ $# == 2 ]] || { echo "Usage: $0 image IMAGE" >&2; exit 2; }
  docker save "$2" -o "$scan_root/source/image.tar"
  mkdir -p artifacts/security
  report="artifacts/security/$(printf '%s' "$2" | tr '/:' '--').json"
  "${trivy[@]}" image --input /src/image.tar --scanners vuln \
    --severity HIGH,CRITICAL --ignorefile /src/security/trivy-ignore.yaml --format json > "$report"
  # An absent inventory is not evidence of a clean image.
  jq -e 'type == "object" and (.Results | type == "array")' "$report" >/dev/null
  # HIGH/CRITICAL findings block even when no fixed package is available.
  jq '[.Results[]?.Vulnerabilities[]?] | {
    total: length,
    fix_available: map(select(.FixedVersion != null and .FixedVersion != "")) | length,
    unfixed_critical: map(select(.Severity == "CRITICAL" and
      (.FixedVersion == null or .FixedVersion == ""))) | length
  }' "$report"
  if jq -e 'any(.Results[]?.Vulnerabilities[]?;
    .Severity == "CRITICAL" and (.FixedVersion == null or .FixedVersion == ""))' "$report" >/dev/null; then
    echo 'Image contains unfixed CRITICAL findings; publication is blocked.' >&2
  fi
  jq -e '[.Results[]?.Vulnerabilities[]? |
    select(.Severity == "HIGH" or .Severity == "CRITICAL")] | length == 0' "$report" >/dev/null
else
  "${trivy[@]}" fs --scanners vuln,secret --severity HIGH,CRITICAL \
    --ignorefile security/trivy-ignore.yaml --exit-code 1 --skip-dirs refs .
  docker run --rm -v "$scan_root/source:/src:ro" -w /src semgrep/semgrep:1.176.0 \
    semgrep scan --config p/python --config p/javascript --config p/typescript \
    --severity ERROR --exclude '**/tests/**' --exclude '**/conftest.py' \
    --exclude '**/*.test.*' --exclude '.agents' --exclude '.codex' \
    --metrics off --error
fi
