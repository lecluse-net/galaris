#!/usr/bin/env bash
# Read-only preflight: exact-commit CI first, then a fresh committed-source scan.
set -euo pipefail
cd "$(dirname "$0")/.."
release_commit=unresolved
stage=configuration
finish() {
  status=$?
  if (( status != 0 )); then
    message="Release blocked: commit=$release_commit stage=$stage exit_code=$status. No publication is approved."
    echo "$message" >&2
    if [[ ${GITHUB_ACTIONS:-} == true ]]; then echo "::error::$message"; fi
    if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then printf '\n**%s**\n' "$message" >> "$GITHUB_STEP_SUMMARY"; fi
  fi
}
trap finish EXIT
for command in git jq docker; do
  command -v "$command" >/dev/null || { echo "Missing prerequisite: $command" >&2; exit 2; }
done
release_commit=$(git rev-parse --verify --end-of-options "${RELEASE_REF:-HEAD}^{commit}")
repository=${GH_REPO:-${GITHUB_REPOSITORY:-}}
if [[ -z "$repository" ]]; then
  if command -v gh >/dev/null; then
    repository=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
  else
    repository=$(git remote get-url origin | sed -En 's#^(git@github.com:|https://github.com/)([^/]+/[^/]+)$#\2#p')
    repository=${repository%.git}
  fi
fi
[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo 'Invalid GH_REPO' >&2; exit 2; }
wait_seconds=${RELEASE_CHECK_TIMEOUT_SECONDS:-0}
[[ "$wait_seconds" =~ ^[0-9]+$ ]] || { echo 'Invalid RELEASE_CHECK_TIMEOUT_SECONDS' >&2; exit 2; }
evidence="artifacts/release-check/$release_commit"
mkdir -p "$evidence"
printf '%s\n' "$release_commit" > "$evidence/SOURCE_COMMIT"
if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
  printf '## Release check\n\nCommit: `%s`\n\n' "$release_commit" >> "$GITHUB_STEP_SUMMARY"
fi
stage=required-ci
workflow_runs() {
  local workflow=$1 destination=$2 page page_file pages_file
  local endpoint="repos/$repository/actions/workflows/$1.yml/runs?head_sha=$release_commit&per_page=100"
  if command -v gh >/dev/null; then
    gh api --method GET --paginate --slurp "$endpoint" > "$destination"
  else
    # Public repositories can be checked without installing or authenticating gh.
    # Private/API failures still fail closed; authenticated Actions use gh above.
    command -v curl >/dev/null || { echo 'Missing prerequisite: gh or curl' >&2; return 2; }
    pages_file="$evidence/$workflow-pages.json"
    : > "$pages_file"
    for ((page=1; page<=10; page++)); do
      page_file="$evidence/$workflow-page-$page.json"
      curl --fail --silent --show-error "https://api.github.com/$endpoint&page=$page" > "$page_file"
      jq -e 'type == "object" and (.workflow_runs | type == "array")' "$page_file" >/dev/null
      cat "$page_file" >> "$pages_file"
      if (( $(jq '.workflow_runs | length' "$page_file") < 100 )); then break; fi
    done
    jq -s . "$pages_file" > "$destination"
  fi
}
deadline=$((SECONDS + wait_seconds))
while :; do
  pending=0
  for workflow in quality security; do
    workflow_runs "$workflow" "$evidence/$workflow.json"
    latest=$(jq -c --arg sha "$release_commit" --arg repo "$repository" '
      [.[].workflow_runs[] | select(.head_sha == $sha and .head_repository.full_name == $repo)
       | select(.event == "push" or .event == "workflow_dispatch" or .event == "schedule")]
      | max_by([.run_number, .run_attempt])' "$evidence/$workflow.json")
    if [[ "$latest" == null ]]; then
      echo "Missing $workflow CI for exact commit $release_commit; run that workflow before publication." >&2
      exit 1
    fi
    state=$(jq -r .status <<< "$latest")
    conclusion=$(jq -r '.conclusion // "pending"' <<< "$latest")
    url=$(jq -r .html_url <<< "$latest")
    echo "$workflow: $state / $conclusion — $url"
    if [[ "$state" != completed ]]; then
      pending=1
    elif [[ "$conclusion" != success ]]; then
      echo "Required $workflow CI ended with $conclusion: $url" >&2
      exit 1
    fi
  done
  (( pending == 0 )) && break
  if (( SECONDS >= deadline )); then
    echo 'Required quality/security CI is pending; wait for completion and rerun the release check.' >&2
    exit 1
  fi
  sleep 30
done
stage=source-security
bash bin/security-check.sh source "$release_commit" 2>&1 | tee "$evidence/source-security.log"
echo "Release check passed for $release_commit: exact-commit CI and fresh source security."
if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
  printf 'Quality and Security passed for this commit; the fresh source scan passed.\n' >> "$GITHUB_STEP_SUMMARY"
fi
