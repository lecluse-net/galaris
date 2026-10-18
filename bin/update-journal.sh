#!/usr/bin/env bash
# Stage metadata only: never copy arbitrary command output or shell arguments.

update_journal_start() {
    local previous_umask
    previous_umask=$(umask)
    umask 077
    if [[ -L artifacts || -L artifacts/updates ]]; then
        echo 'Refusing a symlinked update journal directory.' >&2
        return 1
    fi
    mkdir -p artifacts/updates
    chmod 700 artifacts/updates
    update_journal=$(mktemp "artifacts/updates/update-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX.log")
    local -a previous_journals
    mapfile -t previous_journals < <(find artifacts/updates -maxdepth 1 -type f -name 'update-*.log' ! -name "${update_journal##*/}" -printf '%f\n' | sort -r | tail -n +100)
    local old_journal
    for old_journal in "${previous_journals[@]}"; do
        rm -- "artifacts/updates/$old_journal"
    done
    umask "$previous_umask"
    update_phase=preparation
    trap 'update_journal_finish "$?"' EXIT
    update_journal_event started
    echo "Update journal: $update_journal"
}

update_journal_event() {
    printf '%s stage=%s status=%s exit_code=%s\n' "$(date -u +%FT%TZ)" "$update_phase" "$1" "${2:-0}" >> "$update_journal"
}

update_stage() {
    update_journal_event completed
    update_phase=$1
    update_journal_event started
}

update_journal_finish() {
    local result=$1
    trap - EXIT
    if [[ "$result" -eq 0 ]]; then
        update_journal_event completed
    else
        update_journal_event failed "$result" || echo 'Unable to append the update failure to its journal.' >&2
        echo "Update failed: stage=$update_phase exit_code=$result; journal=$update_journal" >&2
    fi
    exit "$result"
}
