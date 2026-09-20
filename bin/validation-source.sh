#!/usr/bin/env bash
# Shared by local validation and its negative controls. No runtime toolchain on the host.
validation_archive() {
  local root=$1 destination=$2 paths
  paths=$(mktemp)
  (
    cd "$root"
    git ls-files --cached --others --exclude-standard -z |
      sort -zu |
      while IFS= read -r -d '' path; do
        # Deleted tracked files stay deleted. Never carry a deployment environment.
        case "$path" in .env|compose.override.yaml|compose.override.yml|docker-compose.override.yaml|docker-compose.override.yml) continue ;; esac
        if [[ -f "$path" || -L "$path" ]]; then printf '%s\0' "$path"; fi
      done > "$paths"
    # Like Git, retain executable status, not group-write changes from generators.
    tar --null --verbatim-files-from --files-from "$paths" \
      --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
      --mode='a=rX,u+w' \
      -cf "$destination"
  )
  local result=$?
  rm -f "$paths"
  return "$result"
}
