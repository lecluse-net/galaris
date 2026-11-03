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

trivy=(docker run --rm -v "$scan_root/source:/src:ro" -w /src aquasec/trivy:0.76.1)
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
  # Keep every blocking cause readable in CI, even without downloading artifacts.
  jq -r '.Results[]? as $result | $result.Vulnerabilities[]? |
    select(.Severity == "HIGH" or .Severity == "CRITICAL") |
    [$result.Target, .VulnerabilityID, .Severity, .PkgName, .InstalledVersion,
     (.FixedVersion // "unavailable"), (.Status // "unknown"),
     (.SeveritySource // "unspecified"), (.PrimaryURL // "")] | @tsv' "$report"
  echo "Complete vulnerability inventory: $report"
  assessment=$report
  vex=security/ssh-kernel-headers.openvex.json
  # This is an artifact-specific assessment, never a blanket ignore-unfixed rule.
  # Preserve the raw report and verify the exact saved image before applying VEX.
  if jq -e '.Metadata.OS.Family == "ubuntu" and .Metadata.OS.Name == "26.04" and
      .Metadata.ImageConfig.config.Labels["org.opencontainers.image.title"] == "galaris-ssh-executor"' "$report" >/dev/null &&
    jq -e --slurpfile vex "$vex" 'any(.Results[]?.Vulnerabilities[]?;
      . as $finding | any($vex[0].statements[];
        .vulnerability.name == $finding.VulnerabilityID and
        any(.products[]; .["@id"] == $finding.PkgIdentifier.PURL)))' "$report" >/dev/null; then
    expires=$(jq -er '.x_galaris_review_expires | select(test("^[0-9]{4}-[0-9]{2}-[0-9]{2}$"))' "$vex")
    [[ "$(date -u +%F)" < "$expires" ]] || { echo "SSH kernel VEX review expired: $expires" >&2; exit 1; }
    saved_image=$(jq -er '.Metadata.ImageID | select(test("^sha256:[a-f0-9]{64}$"))' "$report")
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
      -v "$PWD/security/verify-kernel-headers.py:/verify.py:ro" --entrypoint python3 \
      "$saved_image" /verify.py > "${report%.json}.header-proof.json"
    jq -e '.package == "linux-libc-dev" and .verified_headers > 0 and
      .kernel_payload_present == false' "${report%.json}.header-proof.json" >/dev/null
    assessment="${report%.json}.assessed.json"
    "${trivy[@]}" image --input /src/image.tar --scanners vuln --severity HIGH,CRITICAL \
      --ignorefile /src/security/trivy-ignore.yaml --vex "/src/$vex" --show-suppressed \
      --format json > "$assessment"
    jq -e 'type == "object" and (.Results | type == "array")' "$assessment" >/dev/null
    jq -e --slurpfile raw "$report" --slurpfile vex "$vex" '
      def identity: [.VulnerabilityID,.PkgIdentifier.PURL,.PkgName,.InstalledVersion];
      ([$raw[0].Results[]?.Vulnerabilities[]? | identity] | sort) ==
      ([.Results[]?.Vulnerabilities[]? | identity] +
       [.Results[]?.ExperimentalModifiedFindings[]?.Finding | identity] | sort) and
      all(.Results[]?.ExperimentalModifiedFindings[]?;
        .Status == "not_affected" and .Statement == "vulnerable_code_not_present" and
        .Finding.PkgName == "linux-libc-dev" and
        (.Finding as $finding | any($vex[0].statements[];
          .vulnerability.name == $finding.VulnerabilityID and
          any(.products[]; .["@id"] == $finding.PkgIdentifier.PURL))))' "$assessment" >/dev/null
    jq '{active:([.Results[]?.Vulnerabilities[]?]|length),
      assessed_not_affected:([.Results[]?.ExperimentalModifiedFindings[]?]|length)}' "$assessment"
    jq -r '.Results[]?.ExperimentalModifiedFindings[]? |
      [.Finding.VulnerabilityID,.Finding.PkgName,.Finding.InstalledVersion,.Status,.Statement] | @tsv' "$assessment"
    echo "Scoped SSH assessment: $assessment; proof=${report%.json}.header-proof.json; expires=$expires"
  fi
  if jq -e 'any(.Results[]?.Vulnerabilities[]?;
    .Severity == "CRITICAL" and (.FixedVersion == null or .FixedVersion == ""))' "$assessment" >/dev/null; then
    echo 'Image contains unfixed CRITICAL findings; publication is blocked.' >&2
  fi
  jq -e '[.Results[]?.Vulnerabilities[]? |
    select(.Severity == "HIGH" or .Severity == "CRITICAL")] | length == 0' "$assessment" >/dev/null
else
  "${trivy[@]}" fs --scanners vuln,secret --severity HIGH,CRITICAL \
    --ignorefile security/trivy-ignore.yaml --exit-code 1 --skip-dirs refs .
  docker run --rm -v "$scan_root/source:/src:ro" -w /src semgrep/semgrep:1.176.0 \
    semgrep scan --config p/python --config p/javascript --config p/typescript \
    --severity ERROR --exclude '**/tests/**' --exclude '**/conftest.py' \
    --exclude '**/*.test.*' --exclude '.agents' --exclude '.codex' \
    --metrics off --error
fi
