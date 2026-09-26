#!/usr/bin/env bash
# The host selects inputs and publishes fixed outputs; executable sources run offline.
set -euo pipefail
cd "$(dirname "$0")/.."
usage() { printf 'Usage: %s {prepare|generate|maps-check|check|revision|inventory|architecture-check|architecture-baseline}\n' "$0" >&2; exit 2; }
[[ $# == 1 ]] || usage
op=$1
case "$op" in prepare|generate|maps-check|check|revision|inventory|architecture-check|architecture-baseline) ;; *) usage ;; esac
root=$(pwd -P)
work=$(mktemp -d "${TMPDIR:-/tmp}/galaris-docs.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
snapshot="$work/repo"; output="$work/output"
mkdir -p "$snapshot" "$output"
fail() { printf '%s\n' "$*" >&2; exit 1; }
safe_path() {
  local base=$1 rel=$2 probe="$1/$2"
  while [[ "$probe" != "$base" ]]; do
    [[ ! -L "$probe" ]] || fail "Rejected symbolic link: $rel"
    probe=${probe%/*}
  done
}
selected() {
  case "/$1/" in */node_modules/*|*/__pycache__/*|*/.git/*|*/.env/*|*/artifacts/*|*/.venv/*) return 1 ;; esac
  # Match the corpus loader's case-insensitive formats in every shipped root.
  case "$1" in
    docs/*|project/decisions/*|project/plans/*)
      case "${1,,}" in *.md|*.json|*.html) return 0 ;; esac ;;
  esac
  # Locale parity and local links also inspect documentation assets.
  case "$1" in
    docs/*)
      case "${1,,}" in *.txt|*.svg|*.png|*.jpg|*.jpeg|*.gif|*.webp|*.pdf|*.css) return 0 ;; esac ;;
  esac
  case "$1" in
    AGENTS.md|.env.example|Makefile|back/modules.py|back/pyproject.toml|back/uv.lock|back/architecture.toml|back/architecture-baseline.json|front/architecture-baseline.json|front/package.json|front/package-lock.json|front/modules.ts|front/scripts/navigation-context.mjs) return 0 ;;
    back/core/*.py|back/app/*.py|back/bridge/*.py|back/scripts/*.py|back/tests/*.py|back/tests/*.md|front/core/*.ts|front/app/*.ts|front/bridge/*.ts|front/core/*.vue|front/app/*.vue|front/bridge/*.vue|front/*.mjs|project/audits/*.md|.agents/skills/*/SKILL.md|.agents/skills/*/agents/openai.yaml) return 0 ;;
  esac
  return 1
}
# Path metadata, never Git configuration, preserves tracked-only architecture checks.
inventory() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files --cached --others --exclude-standard -z
  else
    find . \( -name .git -o -name node_modules -o -name .venv \) -prune -o \( -type f -o -type l \) -print0
  fi | sort -zu
}
tracked() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files -z -- CLAUDE.md .claude .codex/skills
  else
    for name in CLAUDE.md .claude .codex/skills; do
      [[ ! -e "$name" && ! -L "$name" ]] || printf '%s\0' "$name"
    done
  fi
}
collect() {
  local destination=$1 rel src
  inventory > "$work/paths"
  : > "$destination"
  while IFS= read -r -d '' rel; do
    rel=${rel#./}; selected "$rel" || continue
    safe_path "$root" "$rel"
    src="$root/$rel"
    [[ -e "$src" ]] || continue
    [[ -f "$src" ]] || fail "Non-regular source: $rel"
    printf '%s\0' "$rel" >> "$destination"
    sha256sum < "$src" >> "$destination"
    if [[ "$destination" == "$work/before" ]]; then
      printf '%s\n' "$rel" >> "$work/selection"
      mkdir -p "$snapshot/$(dirname "$rel")"
      cp -- "$src" "$snapshot/$rel"
      cmp -s "$src" "$snapshot/$rel" || fail "Source changed while copying: $rel"
    fi
  done < "$work/paths"
  tracked >> "$destination"
}
collect "$work/before"
tracked > "$snapshot/.documentation-tracked-paths"
# Inspection op: report the exact analysis inputs without building or running an image.
if [[ "$op" == inventory ]]; then
  cat "$work/selection"
  exit 0
fi
# Only immutable tooling manifests enter build contexts, never application sources.
for runtime in python node; do
  mkdir -p "$work/$runtime"
  case "$runtime" in python) files=(Dockerfile requirements.txt) ;; node) files=(Dockerfile package.json package-lock.json) ;; esac
  for name in "${files[@]}"; do
    rel="tooling/documentation/$runtime/$name"
    safe_path "$root" "$rel"
    [[ -f "$rel" ]] || fail "Missing tooling manifest: $rel"
    cp -- "$rel" "$work/$runtime/$name"
  done
done
docker build -q -t galaris-documentation-python:local "$work/python" >/dev/null
docker build -q -t galaris-documentation-node:local "$work/node" >/dev/null
common=(--rm --network none --read-only --cap-drop=ALL --security-opt no-new-privileges:true --pids-limit 128 --memory 1g --tmpfs /tmp:size=128m,mode=1777 --user "$(id -u):$(id -g)" --mount "type=bind,src=$snapshot,dst=/repo,readonly")
run() {
  local runtime=$1 writable=$2; shift 2
  local options=("${common[@]}")
  [[ "$writable" == no ]] || options+=(--mount "type=bind,src=$output,dst=/output")
  if [[ "$runtime" == python ]]; then
    docker run "${options[@]}" --entrypoint python -w /repo -e PYTHONPATH=/repo/back -e PYTHONDONTWRITEBYTECODE=1 galaris-documentation-python:local "$@"
  else
    # /repo's parent contains only the image's locked TypeScript dependency.
    docker run "${options[@]}" --entrypoint node -w /repo/front galaris-documentation-node:local "$@"
  fi
}
outputs=()
for locale in fr en; do
  for name in project-map navigation; do
    for extension in json md; do outputs+=("docs/$locale/architecture/generated/$name.$extension"); done
  done
done
verify_outputs() {
  local rel candidate found
  while IFS= read -r -d '' candidate; do
    rel=${candidate#"$output/"}; found=no
    [[ -d "$candidate" && ! -L "$candidate" ]] && continue
    for expected in "${outputs[@]}"; do [[ "$rel" != "$expected" ]] || found=yes; done
    [[ "$found" == yes ]] || fail "Unexpected generated output: $rel"
    safe_path "$output" "$rel"
    [[ -f "$candidate" ]] || fail "Non-regular output: $rel"
  done < <(find "$output" -mindepth 1 -print0)
  for rel in "${outputs[@]}"; do
    safe_path "$output" "$rel"; safe_path "$root" "$rel"
    [[ -f "$output/$rel" ]] || fail "Missing output: $rel"
    [[ ! -e "$root/$rel" || -f "$root/$rel" ]] || fail "Non-regular destination: $rel"
  done
}
maps_check() {
  run python no back/scripts/project_context.py --root /repo --check
  run node no scripts/navigation-context.mjs --root /repo --check
}
case "$op" in
  prepare|generate)
    run python yes back/scripts/project_context.py --root /repo --output /output
    run node yes scripts/navigation-context.mjs --root /repo --output /output
    verify_outputs
    for rel in "${outputs[@]}"; do mkdir -p "$snapshot/$(dirname "$rel")"; cp -- "$output/$rel" "$snapshot/$rel"; done
    if [[ "$op" == prepare ]]; then
      maps_check
      run python no -m app.documentation check --root /repo
      run python no back/scripts/architecture_check.py --root /repo
    fi ;;
  maps-check) maps_check ;;
  check) maps_check; run python no -m app.documentation check --root /repo; run python no back/scripts/architecture_check.py --root /repo ;;
  revision) run python no -m app.documentation revision --root /repo ;;
  architecture-check) run python no back/scripts/architecture_check.py --root /repo ;;
  architecture-baseline)
    outputs=(back/architecture-baseline.json front/architecture-baseline.json)
    run python yes back/scripts/architecture_check.py --root /repo --output /output --update-baseline ;;
esac
case "$op" in
  prepare|generate|architecture-baseline)
    verify_outputs
    collect "$work/after"
    cmp -s "$work/before" "$work/after" || fail 'Sources changed during generation; nothing published'
    # Preflight every destination before publishing any file. Each replacement is atomic.
    for rel in "${outputs[@]}"; do
      safe_path "$root" "$rel"
      mkdir -p "$root/$(dirname "$rel")"
      [[ -w "$root/$(dirname "$rel")" ]] || fail "Destination is not writable: $rel"
    done
    for rel in "${outputs[@]}"; do
      cmp -s "$output/$rel" "$root/$rel" && continue
      safe_path "$root" "$rel"
      temp=$(mktemp "$root/$(dirname "$rel")/.documentation.XXXXXX")
      cp -- "$output/$rel" "$temp"
      chmod 644 "$temp"
      mv -fT -- "$temp" "$root/$rel"
    done ;;
esac
