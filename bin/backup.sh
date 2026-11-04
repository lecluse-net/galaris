#!/usr/bin/env bash
# Offline maintenance using the installed backend image and its real data mount.
set -euo pipefail
cd "$(dirname "$0")/.."
operation=${1:?save or restore is required}
shift
[[ "$operation" == save || "$operation" == restore ]] || exit 2
source bin/update-journal.sh
update_journal_start
update_stage backup-preflight
umask 077
[[ ! -L artifacts/backups ]] || { echo 'Refusing a symlinked backup directory.' >&2; exit 2; }
mkdir -p artifacts/backups
archive=${GALARIS_BACKUP_ARCHIVE:-}
if [[ "$operation" == save ]]; then
    archive=${archive:-artifacts/backups/galaris-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz}
    [[ ! -e "$archive" && ! -L "$archive" ]] || { echo 'Backup already exists.' >&2; exit 2; }
    mkdir -p -- "$(dirname "$archive")"
else
    [[ -n "$archive" && -f "$archive" && ! -L "$archive" ]] || { echo 'Use make restore FILE=<archive> or make restore <archive>.' >&2; exit 2; }
fi
archive=$(realpath -m -- "$archive")
archive_directory=$(dirname "$archive")
archive_name=$(basename "$archive")
backend=$(docker compose "$@" ps --all --quiet backend)
[[ -n "$backend" && "$backend" != *$'\n'* ]] || { echo 'Exactly one installed backend is required.' >&2; exit 2; }
image=$(docker inspect --format '{{.Image}}' "$backend")
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Cannot identify the installed backend image.' >&2; exit 2; }
data_source=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$backend")
[[ -n "$data_source" ]] || { echo 'Installed backend has no persistent /data mount.' >&2; exit 2; }
data_source=$(realpath -m -- "$data_source")
[[ "$data_source" != *$'\n'* ]] || { echo 'Unsupported newline in data mount path.' >&2; exit 2; }
case "$archive/" in "$data_source/"*) echo 'Store backups outside the data directory.' >&2; exit 2 ;; esac
override=$(mktemp "${TMPDIR:-/tmp}/galaris-backup-compose.XXXXXX.yaml")
environment_file=$(mktemp "${TMPDIR:-/tmp}/galaris-backup-env.XXXXXX.json")
trap 'result=$?; rm -f -- "$override" "$environment_file" || true; update_journal_finish "$result"' EXIT
docker inspect --format '{{json .Config.Env}}' "$backend" > "$environment_file"
quoted_data_source=${data_source//\'/\'\'}
printf "services:\n  backend:\n    image: %s\n    pull_policy: never\n    volumes:\n      - type: bind\n        source: '%s'\n        target: /data\n" "$image" "$quoted_data_source" > "$override"
compose=(docker compose "$@" -f "$override")
helper=("${compose[@]}" run --rm --no-deps --pull never -T --user 0:0
    -e "GALARIS_BACKUP_IMAGE=$image"
    -e "GALARIS_BACKUP_UID=$(id -u)" -e "GALARIS_BACKUP_GID=$(id -g)"
    -v "$PWD/back/core/backup.py:/backup-command.py:ro"
    -v "$PWD/.env:/installation.env:ro"
    -v "$environment_file:/installed-environment.json:ro"
    -v "$archive_directory:/backup"
    --entrypoint python backend /backup-command.py)
configured=$(docker compose "$@" config --services)
configured_lines=$'\n'"$configured"$'\n'
running=$(docker compose "$@" ps --status running --services)
services=()
while IFS= read -r service; do
    if [[ -n "$service" && "$service" != postgres && "$configured_lines" == *$'\n'"$service"$'\n'* ]]; then
        services+=("$service")
    fi
done <<< "$running"
stopped=false
finish() {
    local result=$1 resume_result=0 failed_phase=$update_phase
    trap - EXIT
    # A restoration deliberately remains offline for version/rsync coordination.
    # A failed restore also remains offline so no writer races recovery.
    if [[ "$operation" == save && "$stopped" == true && ${#services[@]} -gt 0 && "${GALARIS_BACKUP_KEEP_STOPPED:-}" != 1 ]]; then
        if [[ "$result" -ne 0 ]]; then
            update_journal_event failed "$result" || echo 'Unable to persist the original backup failure.' >&2
        fi
        update_stage backup-resume || { [[ "$result" -ne 0 ]] || result=74; }
        update_journal_command backup-resume "${compose[@]}" up -d --no-build --no-recreate \
            --pull never --wait --wait-timeout 300 "${services[@]}" || resume_result=$?
        if [[ "$resume_result" -ne 0 ]]; then
            echo "Backup service recovery failed: exit_code=$resume_result" >&2
            [[ "$result" -ne 0 ]] || result=$resume_result
        fi
        if [[ "$1" -ne 0 ]]; then update_phase=$failed_phase; fi
    fi
    rm -f -- "$override" || { [[ "$result" -ne 0 ]] || result=74; }
    rm -f -- "$environment_file" || { [[ "$result" -ne 0 ]] || result=74; }
    update_journal_finish "$result"
}
trap 'finish "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ "$operation" == restore ]]; then
    # Validate checksums, paths, PostgreSQL version and encryption key before downtime.
    update_journal_command backup-verify "${helper[@]}" verify "/backup/$archive_name"
fi
update_stage backup-quiescence
if (( ${#services[@]} )); then
    stopped=true
    update_journal_command backup-stop "${compose[@]}" stop "${services[@]}"
fi
update_stage "backup-$operation"
update_journal_command "backup-$operation" "${helper[@]}" "$operation" "/backup/$archive_name"
if [[ "$operation" == save ]]; then
    echo "Backup archive: $archive"
    if [[ "${GALARIS_BACKUP_KEEP_STOPPED:-}" == 1 ]]; then
        echo 'Application services remain stopped for the separate /data/files rsync snapshot.'
    fi
else
    echo 'Database and data restored. /data/files was left intact.'
    echo 'Services remain stopped: coordinate the separate rsync copy and the application version before starting.'
fi
