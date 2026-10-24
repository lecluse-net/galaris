#!/usr/bin/env bash
# Qualification only: no existing application database or external messaging connection.
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
  cat <<'EOF'
Usage: make agent-team-pilot ARGS='prepare|run [options]'
  --case baseline|missing|conflict|amendment|amendments|peer_failure|comparison
  --mode spontaneous|directed|solo           (default: spontaneous)
  --config /absolute/provider.json           non-secret endpoint/model configuration
  --key-file /absolute/provider-key          read-only credential file; run only
  --api-only                                skip frontend/browser preparation
  --restart-after-amendment                  SIGKILL and resume after a pending amendment
  --restart-after-write                      SIGKILL after a committed target write, before delivery

prepare creates synthetic fixtures, checks authentication and reads the real API.
It never submits a mission and disables the provider. run submits one real mission.
Each invocation owns a disposable database and writes private evidence under artifacts/agent-team/.
EOF
}

action="${1:-prepare}"
if [[ "$action" == --help || "$action" == -h ]]; then usage; exit 0; fi
if [[ $# -gt 0 ]]; then shift; fi
TEAM_PILOT_CASE=baseline
TEAM_PILOT_MODE=spontaneous
TEAM_PILOT_CONFIG="$PWD/back/tests/agent_team_pilot/provider.example.json"
TEAM_PILOT_KEY_FILE=/dev/null
api_only=false
TEAM_PILOT_RESTART=0
TEAM_PILOT_RESTART_PHASE=pending_amendment
while [[ $# -gt 0 ]]; do
  case "$1" in
    --case|--mode|--config|--key-file)
      if [[ $# -lt 2 ]]; then usage >&2; exit 2; fi
      case "$1" in
        --case) TEAM_PILOT_CASE="$2" ;;
        --mode) TEAM_PILOT_MODE="$2" ;;
        --config) TEAM_PILOT_CONFIG=$(realpath "$2") ;;
        --key-file) TEAM_PILOT_KEY_FILE=$(realpath "$2") ;;
      esac
      shift 2 ;;
    --api-only) api_only=true; shift ;;
    --restart-after-amendment) TEAM_PILOT_RESTART=1; shift ;;
    --restart-after-write) TEAM_PILOT_RESTART=1; TEAM_PILOT_RESTART_PHASE=committed_write; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
case "$action" in prepare|run) ;; *) usage >&2; exit 2 ;; esac
case "$TEAM_PILOT_CASE" in baseline|missing|conflict|amendment|amendments|peer_failure|comparison) ;; *) usage >&2; exit 2 ;; esac
case "$TEAM_PILOT_MODE" in spontaneous|directed|solo) ;; *) usage >&2; exit 2 ;; esac
if [[ "$TEAM_PILOT_RESTART" == 1 && ( "$action" != run || "$TEAM_PILOT_CASE" != amendment ) ]]; then
  echo '--restart-after-amendment requires run --case amendment.' >&2; exit 2
fi
if [[ ( "$TEAM_PILOT_CASE" == amendment || "$TEAM_PILOT_CASE" == amendments || "$TEAM_PILOT_CASE" == peer_failure ) && "$TEAM_PILOT_MODE" == solo ]]; then
  echo 'The amendment trigger requires two active colleagues; choose another mode.' >&2; exit 2
fi
if [[ "$action" == run && "$TEAM_PILOT_CONFIG" == "$PWD/back/tests/agent_team_pilot/provider.example.json" ]]; then
  echo 'run requires an explicit --config with a real model. No provider was called.' >&2; exit 2
fi
if [[ ! -f "$TEAM_PILOT_CONFIG" ]]; then echo 'Configuration file missing.' >&2; exit 2; fi
if [[ "$TEAM_PILOT_KEY_FILE" != /dev/null && ! -f "$TEAM_PILOT_KEY_FILE" ]]; then echo 'Credential file missing.' >&2; exit 2; fi
if [[ "$api_only" == true && "$action" == run ]]; then
  echo 'Real missions must be submitted through the browser; --api-only is for prepare.' >&2; exit 2
fi
export TEAM_PILOT_CASE TEAM_PILOT_MODE TEAM_PILOT_CONFIG TEAM_PILOT_KEY_FILE
TEAM_PILOT_EXECUTE=0
if [[ "$action" == run ]]; then TEAM_PILOT_EXECUTE=1; fi
export TEAM_PILOT_EXECUTE
TEAM_PILOT_UID=$(id -u)
TEAM_PILOT_GID=$(id -g)
export TEAM_PILOT_UID TEAM_PILOT_GID
umask 077
mkdir -p artifacts/agent-team
TEAM_PILOT_ARTIFACTS=$(mktemp -d "$PWD/artifacts/agent-team/run.XXXXXX")
export TEAM_PILOT_ARTIFACTS
TEAM_PILOT_RUN_ID=$(basename "$TEAM_PILOT_ARTIFACTS")
export TEAM_PILOT_RUN_ID TEAM_PILOT_RESTART TEAM_PILOT_RESTART_PHASE
project="galaris-team-pilot-$$"
compose=(docker compose -p "$project" -f compose.agent-team.yaml)
printf 'Pilot %s / %s / %s\nEvidence: %s\n' "$action" "$TEAM_PILOT_CASE" "$TEAM_PILOT_MODE" "$TEAM_PILOT_ARTIFACTS"
git rev-parse HEAD > "$TEAM_PILOT_ARTIFACTS/source-commit.txt"
git diff --binary | sha256sum > "$TEAM_PILOT_ARTIFACTS/worktree-diff.sha256"
source_hashes() {
  find back front e2e -type d \( -name node_modules -o -name .venv -o -name __pycache__ -o -name dist -o -name test-results \) -prune -o \
    -type f \( -name '*.py' -o -name '*.json' -o -name '*.mjs' -o -name '*.md' -o -name '*.vue' -o -name '*.ts' -o -name '*.toml' -o -name '*.lock' -o -name '*.css' -o -name '*.scss' \) -print0 \
    | sort -z | xargs -0 sha256sum
  sha256sum Makefile bin/agent-team-pilot*.sh compose.agent-team.yaml
}
source_hashes > "$TEAM_PILOT_ARTIFACTS/source-files.sha256"
stage=backend-preparation

cleanup() {
  original=$?
  trap - EXIT
  printf '%s\n' "$original" > "$TEAM_PILOT_ARTIFACTS/primary-exit-status.txt"
  printf '%s\n' "$stage" > "$TEAM_PILOT_ARTIFACTS/last-stage.txt"
  # Preserve primary failure and its evidence even when diagnostics/cleanup fail.
  if ! "${compose[@]}" logs --no-color backend db-team 2>&1 | \
      "${compose[@]}" run --rm --no-deps -T observer python -m tests.agent_team_pilot.diagnostics; then
    echo 'Service diagnostics could not be persisted.' >&2
    printf 'Service diagnostic collection failed.\n' > "$TEAM_PILOT_ARTIFACTS/diagnostics-error.txt"
    if [[ "$original" == 0 ]]; then original=1; fi
  fi
  if ! "${compose[@]}" down --volumes --remove-orphans > "$TEAM_PILOT_ARTIFACTS/cleanup.log" 2>&1; then
    echo "Pilot cleanup failed; inspect $TEAM_PILOT_ARTIFACTS/cleanup.log" >&2
    if [[ "$original" == 0 ]]; then original=1; fi
  fi
  if ! source_hashes > "$TEAM_PILOT_ARTIFACTS/source-files-after.sha256" || \
      ! cmp -s "$TEAM_PILOT_ARTIFACTS/source-files.sha256" "$TEAM_PILOT_ARTIFACTS/source-files-after.sha256"; then
    printf 'Sources changed during the pilot; evidence is not a qualification of one fixed checkout.\n' > "$TEAM_PILOT_ARTIFACTS/source-changed.txt"
    echo 'Sources changed during this pilot; inspect source-changed.txt.' >&2
    if [[ "$original" == 0 ]]; then original=2; fi
  fi
  rm -f "$TEAM_PILOT_ARTIFACTS/_session.json"
  printf '%s\n' "$original" > "$TEAM_PILOT_ARTIFACTS/exit-status.txt"
  exit "$original"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"${compose[@]}" run --rm --no-deps --user 0 -T backend sh -c 'chown "$1:$2" /data && chmod 700 /data' sh "$TEAM_PILOT_UID" "$TEAM_PILOT_GID"
"${compose[@]}" up -d --wait backend
stage=api-preflight
"${compose[@]}" run --rm --no-deps observer python -m tests.agent_team_pilot.runner --preflight
if [[ "$api_only" == false ]]; then
  stage=browser-build
  "${compose[@]}" build frontend browser
  "${compose[@]}" up -d --wait frontend
  stage=browser-preflight
  "${compose[@]}" run --rm --no-deps browser node pilots/agent-team.mjs check
fi
if [[ "$action" == run ]]; then
  if [[ "$TEAM_PILOT_RESTART" == 1 ]]; then
    stage=fault-preparation
    bash bin/agent-team-pilot-restart.sh --prepare "$project"
  fi
  stage=mission-submission
  result=0
  "${compose[@]}" run --rm --no-deps browser node pilots/agent-team.mjs submit || result=$?
  printf '%s\n' "$result" > "$TEAM_PILOT_ARTIFACTS/submission-exit-status.txt"
  if [[ "$result" != 0 && ! -s "$TEAM_PILOT_ARTIFACTS/submission.json" ]]; then
    exit "$result"
  fi
  # An accepted message may already be running despite a browser diagnostic.
  # Collect that work without resubmitting, retaining the primary failure.
  stage=mission-observation
  if [[ "$TEAM_PILOT_RESTART" == 1 ]]; then
    "${compose[@]}" run --rm --no-deps observer &
    observer_pid=$!
    restart_done=false
    restart_status=0
    while kill -0 "$observer_pid" 2>/dev/null; do
      if [[ "$restart_done" == false && -s "$TEAM_PILOT_ARTIFACTS/restart-request.json" ]]; then
        restart_done=true
        stage=backend-interruption
        bash bin/agent-team-pilot-restart.sh "$project" || restart_status=$?
        stage=mission-observation
      fi
      sleep 0.1
    done
    observation_status=0
    wait "$observer_pid" || observation_status=$?
    if [[ "$result" == 0 && "$restart_status" != 0 ]]; then result=$restart_status; fi
  else
    observation_status=0
    "${compose[@]}" run --rm --no-deps observer || observation_status=$?
  fi
  if [[ "$observation_status" != 0 ]]; then
    printf '%s\n' "$observation_status" > "$TEAM_PILOT_ARTIFACTS/observation-exit-status.txt"
    if [[ "$result" == 0 ]]; then result=$observation_status; fi
  fi
  stage=browser-capture
  if "${compose[@]}" run --rm --no-deps browser node pilots/agent-team.mjs capture; then :; else
    capture_status=$?
    printf '%s\n' "$capture_status" > "$TEAM_PILOT_ARTIFACTS/capture-exit-status.txt"
    if [[ "$result" == 0 ]]; then result=$capture_status; fi
  fi
  echo "Report: $TEAM_PILOT_ARTIFACTS/report.md (human content review required)"
  exit "$result"
fi
stage=prepared
echo 'Preparation checked. No mission submitted and no provider inference requested.'
