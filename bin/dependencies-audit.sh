#!/usr/bin/env bash
# Audit a snapshot without installing packages or mounting the application/socket.
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  '') ;;
  --test) ;;
  *) echo "Usage: $0 [--test]" >&2; exit 2 ;;
esac
image=galaris-dependencies-audit
docker build -q -t "$image" tooling/dependencies >/dev/null
isolated=(--rm --read-only --cap-drop ALL --security-opt no-new-privileges:true
  --user "$(id -u):$(id -g)" --pids-limit 128)
if [[ ${1:-} == --test ]]; then
  docker run "${isolated[@]}" --tmpfs /tmp:size=128m,mode=1777 --network none --entrypoint python "$image" -m unittest -v test_audit
  exit
fi
command -v jq >/dev/null || { echo 'jq is required.' >&2; exit 2; }
threshold=${FAIL_ON:-HIGH}
case "$threshold" in UNKNOWN|LOW|MEDIUM|HIGH|CRITICAL) ;; *) echo 'Invalid FAIL_ON severity.' >&2; exit 2 ;; esac
root=$PWD
work=$(mktemp -d "${TMPDIR:-/tmp}/galaris-dependency-audit.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$work/snapshot/repo" "$work/images" "$work/scanner-tmp" artifacts/dependencies/.cache
output=$(mktemp -d "$root/artifacts/dependencies/audit-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
echo "Dependency audit report: ${output#"$root/"}/summary.md"
# Git-visible worktree contents, including uncommitted changes. Reject symlink
# ancestors as well as symlink files; ignored credentials and caches stay outside.
git ls-files -z --cached --others --exclude-standard -- . ':!:refs' ':!:artifacts' |
  while IFS= read -r -d '' entry; do
    case "/$entry/" in */node_modules/*|*/.venv/*|*/.local/*|*/.git/*|*/__pycache__/*) continue ;; esac
    [[ "$entry" != .env && -f "$entry" ]] || continue
    probe="$root/$entry"
    safe=true
    while [[ "$probe" != "$root" ]]; do
      if [[ -L "$probe" ]]; then safe=false; break; fi
      probe=${probe%/*}
    done
    if "$safe"; then printf '%s\0' "$entry"; fi
  done |
  tar --null -T - -cf - | tar -xf - -C "$work/snapshot/repo"
docker run "${isolated[@]}" --tmpfs /tmp:size=128m,mode=1777 --network none \
  -v "$work/snapshot:/snapshot" -v "$output:/report" "$image" \
  inventory --root /snapshot --output /report
printf '[]\n' > "$output/scans.json"
scanner=(docker run "${isolated[@]}" -v "$work/snapshot:/snapshot:ro"
  -v "$work/scanner-tmp:/tmp"
  -v "$work/images:/images:ro" -v "$output:/report" -v "$root/artifacts/dependencies/.cache:/cache"
  aquasec/trivy:0.76.1)
scan() {
  local name=$1 status=0
  shift
  "$@" > "$output/$name.log" 2>&1 || status=$?
  jq --arg name "$name" --argjson status "$status" \
    '. + [{name:$name, report:($name + ".trivy.json"), exit_code:$status}]' \
    "$output/scans.json" > "$output/scans.next.json"
  mv "$output/scans.next.json" "$output/scans.json"
}
echo 'Scanning source dependencies (including development dependencies and inline pins)...'
scan source "${scanner[@]}" fs --scanners vuln --include-dev-deps --list-all-pkgs \
  --ignorefile '' --exit-code 0 --timeout 15m --cache-dir /cache \
  --format json --output /report/source.trivy.json /snapshot
index=0
read -r -a images <<< "${IMAGES:-}"
for target in "${images[@]}"; do
  name="image-$index"
  printf '%s\n' "$target" > "$output/$name.name.txt"
  echo "Scanning built image: $target"
  # Save locally: the scanner never gets the Docker socket or registry credentials.
  if docker image inspect --format '{{.Id}}' "$target" > "$output/$name.identity.txt" 2> "$output/$name.export.log" &&
    docker save "$target" -o "$work/images/$index.tar" 2>> "$output/$name.export.log"; then
    scan "$name" "${scanner[@]}" image --input "/images/$index.tar" --scanners vuln \
      --list-all-pkgs --ignorefile '' --exit-code 0 --timeout 15m \
      --cache-dir /cache --format json --output "/report/$name.trivy.json"
  else
    scan "$name" false
  fi
  rm -f "$work/images/$index.tar"
  index=$((index + 1))
done
echo 'Looking up published package versions and infrastructure references...'
status=0
version_options=()
if [[ ${ALL_VERSIONS:-0} == 1 ]]; then version_options+=(--all-versions); fi
if [[ ${REFRESH_VERSIONS:-0} == 1 ]]; then version_options+=(--refresh-versions); fi
docker run "${isolated[@]}" --tmpfs /tmp:size=128m,mode=1777 -v "$work/snapshot:/snapshot:ro" \
  -v "$root/artifacts/dependencies/.cache:/cache" -v "$output:/report" "$image" \
  report --root /snapshot --output /report --metadata-cache /cache/versions.json \
  --fail-on "$threshold" "${version_options[@]}" || status=$?
if [[ -n ${GITHUB_STEP_SUMMARY:-} && -f "$output/summary.md" ]]; then
  cat "$output/summary.md" >> "$GITHUB_STEP_SUMMARY"
fi
echo "Report: ${output#"$root/"}/summary.md"
echo "JSON: ${output#"$root/"}/report.json"
exit "$status"
