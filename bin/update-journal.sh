#!/usr/bin/env bash
# Persist startup evidence on the host, independently of the backend and database.

update_maintenance_lock() {
    if [[ -L artifacts || -L artifacts/.maintenance.lock ]]; then
        echo 'Refusing a symlinked maintenance lock.' >&2
        return 2
    fi
    mkdir -p artifacts
    exec {update_lock_fd}>>artifacts/.maintenance.lock
    if ! flock -n "$update_lock_fd"; then
        echo 'Another deployment, backup or restoration is running.' >&2
        return 2
    fi
}

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
    # Backup, restore and deployment must not race the same database/data tree.
    update_maintenance_lock
    update_journal=$(mktemp "artifacts/updates/update-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX.log")
    local -a previous_journals
    mapfile -t previous_journals < <(find artifacts/updates -maxdepth 1 -type f -name 'update-*.log' ! -name "${update_journal##*/}" -printf '%f\n' | sort -r | tail -n +100)
    local old_journal
    for old_journal in "${previous_journals[@]}"; do
        rm -- "artifacts/updates/$old_journal"
    done
    umask "$previous_umask"
    update_started_at=$(date -u +%FT%TZ)
    update_backend_pending=false
    update_phase=preparation
    trap 'update_journal_finish "$?"' EXIT
    update_journal_event started
    echo "Update journal: $update_journal"
}

update_journal_event() {
    printf '%s stage=%s status=%s exit_code=%s%s\n' "$(date -u +%FT%TZ)" "$update_phase" "$1" "${2:-0}" "${3:+ command=$3}" >> "$update_journal"
}

update_journal_command() {
    # The identity is a fixed label, never an argument dump containing credentials.
    local identity=$1 result
    local -a statuses
    shift
    if ! update_journal_event command-started 0 "$identity"; then
        echo 'Unable to append update command evidence to its journal.' >&2
        return 74
    fi
    if "$@" 2>&1 | LC_ALL=C awk -f bin/redact-update-log.awk | tee -a "$update_journal"; then
        statuses=("${PIPESTATUS[@]}")
    else
        statuses=("${PIPESTATUS[@]}")
    fi
    result=${statuses[0]}
    if [[ "${statuses[1]}" -ne 0 || "${statuses[2]}" -ne 0 ]]; then
        echo "Unable to redact or persist update diagnostics: command=$identity filter_exit=${statuses[1]} journal_exit=${statuses[2]}" >&2
        [[ "$result" -ne 0 ]] || result=74
    fi
    if ! update_journal_event command-completed "$result" "$identity"; then
        echo 'Unable to append update command result to its journal.' >&2
        [[ "$result" -ne 0 ]] || result=74
    fi
    return "$result"
}

update_journal_watch_backend() {
    update_backend_compose=(docker compose "$@")
    update_backend_pending=true
}

update_journal_collect_backend() {
    local result
    update_backend_pending=false
    # No tail limit: the first DbAdmin error may precede hundreds of later lines.
    # Include successful/staged startups too, since nonfatal issues matter as well.
    if update_journal_command backend-startup-logs "${update_backend_compose[@]}" \
        logs --no-color --timestamps --since "$update_started_at" backend; then
        return 0
    else
        result=$?
    fi
    echo "Unable to collect complete backend startup logs: exit_code=$result; journal=$update_journal" >&2
    update_journal_event diagnostics-incomplete "$result" backend-startup-logs || \
        echo 'Unable to persist the diagnostic collection failure.' >&2
    return "$result"
}

update_stage() {
    update_journal_event completed
    update_phase=$1
    update_journal_event started
}

update_journal_finish() {
    local result=$1
    trap - EXIT
    if [[ "$update_backend_pending" == true ]]; then
        local collection_result=0
        update_journal_collect_backend || collection_result=$?
        if [[ "$collection_result" -ne 0 ]]; then
            [[ "$result" -ne 0 ]] || result=$collection_result
        fi
    fi
    if [[ "$result" -eq 0 ]]; then
        if ! update_journal_event completed; then
            echo 'Unable to append the update result to its journal.' >&2
            result=74
        fi
    else
        update_journal_event failed "$result" || echo 'Unable to append the update failure to its journal.' >&2
        echo "Update failed: stage=$update_phase exit_code=$result; journal=$update_journal" >&2
    fi
    exit "$result"
}
