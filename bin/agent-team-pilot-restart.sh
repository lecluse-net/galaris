#!/usr/bin/env bash
# Fault injection owns only the backend of this invocation's disposable project.
set -euo pipefail
prepare=false
if [[ "${1:-}" == --prepare ]]; then prepare=true; shift; fi
project=${1:?Missing pilot project}
[[ "$project" == galaris-team-pilot-* && "${TEAM_PILOT_RESTART:-0}" == 1 ]]
directory=${TEAM_PILOT_ARTIFACTS:?Missing artifacts}
compose=(docker compose -p "$project" -f compose.agent-team.yaml)
status=1
receipt() {
  original=$?
  trap - EXIT
  phase=error
  if [[ "$original" == 0 && "$status" == 0 ]]; then phase=ready; fi
  printf '{"status":"%s","exit_status":%d,"completed_at":"%s"}\n' "$phase" "$original" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$directory/restart-receipt.json.tmp"
  mv "$directory/restart-receipt.json.tmp" "$directory/restart-receipt.json"
  exit "$original"
}
inspect() {
  docker inspect --format '{"container":"{{.Id}}","pid":{{.State.Pid}},"started_at":"{{.State.StartedAt}}","status":"{{.State.Status}}","exit_code":{{.State.ExitCode}}}' "$1"
}
if [[ "$prepare" == true ]]; then
  backend=$("${compose[@]}" ps -q backend)
  database=$("${compose[@]}" ps -q db-team)
  [[ "$backend" =~ ^[a-f0-9]+$ && "$database" =~ ^[a-f0-9]+$ ]]
  inspect "$backend" > "$directory/backend-before.json"
  inspect "$database" > "$directory/database-before.json"
  printf '%s\n' "$backend" > "$directory/backend-container.txt"
  printf '%s\n' "$database" > "$directory/database-container.txt"
  exit 0
fi
trap receipt EXIT
backend=$(cat "$directory/backend-container.txt")
database=$(cat "$directory/database-container.txt")
[[ "$backend" =~ ^[a-f0-9]+$ && "$database" =~ ^[a-f0-9]+$ ]]
docker kill --signal KILL "$backend"
inspect "$backend" > "$directory/backend-killed.json"
"${compose[@]}" up -d --no-deps --wait --wait-timeout 180 backend > "$directory/restart-start.log" 2>&1
inspect "$backend" > "$directory/backend-after.json"
inspect "$database" > "$directory/database-after.json"
status=0
