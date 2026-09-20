#!/usr/bin/env bash
# Keep the operation parsed in memory even when checkout replaces this script.
set -euo pipefail

fail() {
    echo "❌ $*" >&2
    exit 1
}

main() {
    local version=${VERSION:-} branch remote target local_ref changes fetch_specs spec
    local tracked=false
    [[ -n "$version" ]] || return 0
    if [[ ! -e .git ]]; then
        fail 'VERSION requires a Git checkout in this installation.'
    fi
    git rev-parse --git-dir >/dev/null || fail 'Invalid .git metadata.'
    changes=$(git status --porcelain --untracked-files=normal) || fail 'Cannot inspect the Git working tree.'
    [[ -z "$changes" ]] || \
        fail 'Local source changes found. Commit or set them aside before make update; nothing was overwritten.'

    branch=$(git symbolic-ref --quiet --short HEAD) || branch=''
    [[ "$version" != -* ]] && git check-ref-format "refs/tags/$version" || \
        fail 'VERSION must be an exact tag or branch name.'

    remote=$(git config --get "branch.$branch.remote") || remote=origin
    [[ "$remote" != . ]] || remote=origin
    git remote get-url "$remote" >/dev/null || fail 'No usable Git remote configured.'
    # Explicit heads also support clones initially limited to a single branch.
    git fetch --prune --tags "$remote" "+refs/heads/*:refs/remotes/$remote/*"

    target="refs/tags/$version"
    if git show-ref --verify --quiet "$target"; then
        git checkout --detach --no-overwrite-ignore "$target"
        return
    fi
    target="refs/remotes/$remote/$version"
    git show-ref --verify --quiet "$target" || fail "No tag or remote branch named '$version'."
    local_ref="refs/heads/$version"
    if git show-ref --verify --quiet "$local_ref"; then
        git merge-base --is-ancestor "$local_ref" "$target" || \
            fail "Local branch '$version' has commits absent from its remote; refusing to reset it."
    fi
    # A --single-branch clone also needs a persistent fetch mapping so the new
    # upstream can be resolved on subsequent explicit version selections.
    fetch_specs=$(git config --get-all "remote.$remote.fetch") || fetch_specs=''
    while IFS= read -r spec; do
        case "${spec#+}" in
            "refs/heads/*:refs/remotes/$remote/*"|"refs/heads/$version:refs/remotes/$remote/$version") tracked=true ;;
        esac
    done <<< "$fetch_specs"
    if [[ "$tracked" == false ]]; then
        git remote set-branches --add "$remote" "$version"
    fi
    if git show-ref --verify --quiet "$local_ref"; then
        git checkout --no-overwrite-ignore "$version"
        git merge --ff-only --no-autostash --no-overwrite-ignore "$target"
        git branch --set-upstream-to="$remote/$version" "$version"
    else
        git checkout --no-overwrite-ignore -b "$version" --track "$target"
    fi
}

main "$@"
