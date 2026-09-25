#!/usr/bin/env bash
# Real disposable Git repositories; only the Docker process is replaced.
set -Eeuo pipefail
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
case_dir=$(mktemp -d)
trap 'rm -rf "$case_dir"' EXIT
trap 'echo "Git update test failed at line $LINENO" >&2; tail -n 15 "$case_dir/output.log" >&2' ERR
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
export GIT_AUTHOR_NAME='Update test' GIT_AUTHOR_EMAIL=update@example.invalid
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
export GIT_TERMINAL_PROMPT=0
export GIT_UPDATE_TEST_LOG="$case_dir/docker.log"
export GIT_UPDATE_TEST_MARKER="$case_dir/refreshed"
mkdir -p "$case_dir/tools" "$case_dir/seed/bin"
cat > "$case_dir/tools/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GIT_UPDATE_TEST_LOG"
case " $* " in
    *" app.documentation revision "*) printf '%064d\n' 1 ;;
    *" config --services "*) echo backend ;;
esac
SH
chmod +x "$case_dir/tools/docker"
export PATH="$case_dir/tools:$PATH"
git init --quiet --bare --initial-branch=main "$case_dir/origin.git"
git init --quiet --initial-branch=main "$case_dir/seed"
cp "$repo_dir/Makefile" "$case_dir/seed/"
cp "$repo_dir/bin/"{update-source,start,init-data-volume,refresh-documentation}.sh "$case_dir/seed/bin/"
for script in update-secrets init-search-config finalize-internal-secrets update-release; do
    printf '#!/usr/bin/env bash\nexit 0\n' > "$case_dir/seed/bin/$script.sh"
done
printf '.env\ncompose.override.yaml\n' > "$case_dir/seed/.gitignore"
printf 'initial\n' > "$case_dir/seed/version.txt"
git -C "$case_dir/seed" add .
git -C "$case_dir/seed" commit --quiet -m 'Initial test fixture'
git -C "$case_dir/seed" remote add origin "$case_dir/origin.git"
git -C "$case_dir/seed" push --quiet -u origin main
git clone --quiet "$case_dir/origin.git" "$case_dir/install"
install_dir="$case_dir/install"
printf 'APP_ENV=dev\nPOSTGRES_MODE=external\nWEBRTC_TURN_MODE=disabled\n' > "$install_dir/.env"
printf '# custom ports\n' > "$install_dir/compose.override.yaml"
cp "$install_dir/.env" "$case_dir/env.before"
cp "$install_dir/compose.override.yaml" "$case_dir/override.before"

run_update() {
    : > "$GIT_UPDATE_TEST_LOG"
    env -u APP_ENV -u VERSION -u RELEASE_DIR -u GIT_UPDATE -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$install_dir" update "$@" > "$case_dir/output.log" 2>&1
}
expect_failure() {
    local before
    before=$(git -C "$install_dir" rev-parse HEAD)
    if run_update "$@"; then
        echo 'Unexpected successful update' >&2
        exit 1
    fi
    test "$before" = "$(git -C "$install_dir" rev-parse HEAD)"
    test ! -s "$GIT_UPDATE_TEST_LOG"
}

# Only an explicit version advances HEAD and reloads the fetched Makefile.
printf 'updated\n' > "$case_dir/seed/version.txt"
cat >> "$case_dir/seed/Makefile" <<'MAKE'

.PHONY: fetched-version
update: fetched-version
fetched-version:
	@echo refreshed > "$$GIT_UPDATE_TEST_MARKER"
MAKE
git -C "$case_dir/seed" add .
git -C "$case_dir/seed" commit --quiet -m 'Updated test fixture'
git -C "$case_dir/seed" tag -a v1 -m 'Annotated test release'
git -C "$case_dir/seed" branch v1 HEAD~1
git -C "$case_dir/seed" branch feature/demo
git -C "$case_dir/seed" push --quiet origin main refs/heads/v1 feature/demo --tags
run_update
test "$(cat "$install_dir/version.txt")" = initial
test ! -f "$GIT_UPDATE_TEST_MARKER"
test ! -f "$install_dir/.git/FETCH_HEAD"
run_update VERSION=main
test "$(cat "$install_dir/version.txt")" = updated
test -f "$GIT_UPDATE_TEST_MARKER"
grep -q ' build$' "$GIT_UPDATE_TEST_LOG"
cmp "$case_dir/env.before" "$install_dir/.env"
cmp "$case_dir/override.before" "$install_dir/compose.override.yaml"

# Exact tag wins over a branch of the same name; plain updates keep detached HEAD.
run_update VERSION=v1
test "$(git -C "$install_dir" rev-parse HEAD)" = "$(git -C "$case_dir/seed" rev-parse 'refs/tags/v1^{commit}')"
if git -C "$install_dir" symbolic-ref --quiet HEAD; then exit 1; fi
run_update
if git -C "$install_dir" symbolic-ref --quiet HEAD; then exit 1; fi
run_update VERSION=feature/demo
test "$(git -C "$install_dir" branch --show-current)" = feature/demo
test "$(git -C "$install_dir" rev-parse --abbrev-ref '@{upstream}')" = origin/feature/demo
run_update VERSION=main
expect_failure VERSION=missing
grep -q 'No tag or remote branch' "$case_dir/output.log"
expect_failure VERSION='main~1'
expect_failure VERSION=--help
expect_failure 'VERSION=missing;touch injected'
test ! -e "$install_dir/injected"
expect_failure VERSION=v1 RELEASE_DIR=/unused-release

# An ignored operator file must never be replaced by a versioned incoming file.
git -C "$case_dir/seed" checkout --quiet -b config-clash feature/demo
printf 'incoming configuration\n' > "$case_dir/seed/.env"
git -C "$case_dir/seed" add --force .env
git -C "$case_dir/seed" commit --quiet -m 'Conflicting test configuration'
git -C "$case_dir/seed" push --quiet origin config-clash
git -C "$case_dir/seed" checkout --quiet main
expect_failure VERSION=config-clash
cmp "$case_dir/env.before" "$install_dir/.env"
git -C "$install_dir" checkout --quiet -b config-clash feature/demo
git -C "$install_dir" branch --set-upstream-to=origin/config-clash >/dev/null
expect_failure VERSION=config-clash
cmp "$case_dir/env.before" "$install_dir/.env"
git -C "$install_dir" checkout --quiet main

# Dirty, staged and untracked source files must survive an unsuccessful update.
printf 'local edit\n' >> "$install_dir/version.txt"
expect_failure VERSION=v1
grep -q 'local edit' "$install_dir/version.txt"
# Local deployment and automatic startup recovery never fetch or switch sources.
run_update
grep -q ' build$' "$GIT_UPDATE_TEST_LOG"
env -u APP_ENV -u VERSION -u RELEASE_DIR -u GIT_UPDATE -u MAKEOVERRIDES MAKEFLAGS= \
    make --no-print-directory -C "$install_dir" start > "$case_dir/output.log" 2>&1
grep -q 'local edit' "$install_dir/version.txt"
git -C "$install_dir" add version.txt
run_update
expect_failure VERSION=v1
git -C "$install_dir" restore --staged --worktree version.txt
touch "$install_dir/untracked.txt"
run_update
expect_failure VERSION=v1
test -f "$install_dir/untracked.txt"
rm "$install_dir/untracked.txt"
git -C "$install_dir" branch --unset-upstream
run_update
run_update VERSION=main
test "$(git -C "$install_dir" rev-parse --abbrev-ref '@{upstream}')" = origin/main

# Failed resolution/fetch and divergent branches must not touch containers.
git -C "$install_dir" remote set-url origin "$case_dir/absent.git"
run_update
expect_failure VERSION=v1
git -C "$install_dir" remote set-url origin "$case_dir/origin.git"
printf 'local commit\n' > "$install_dir/local.txt"
git -C "$install_dir" add local.txt
git -C "$install_dir" commit --quiet -m 'Local test change'
printf 'remote commit\n' > "$case_dir/seed/remote.txt"
git -C "$case_dir/seed" add remote.txt
git -C "$case_dir/seed" commit --quiet -m 'Remote test change'
git -C "$case_dir/seed" push --quiet origin main
run_update
expect_failure VERSION=main
run_update VERSION=feature/demo
expect_failure VERSION=main

# A single-branch clone can select and subsequently follow another branch.
git clone --quiet --single-branch --branch main "$case_dir/origin.git" "$case_dir/single-branch"
install_dir="$case_dir/single-branch"
cp "$case_dir/env.before" "$install_dir/.env"
run_update VERSION=feature/demo
test "$(git -C "$install_dir" rev-parse --abbrev-ref '@{upstream}')" = origin/feature/demo
run_update

# A Git worktree uses a .git file; the same reference resolution must work there.
git -C "$case_dir/seed" worktree add --quiet --detach "$case_dir/worktree" refs/tags/v1
test -f "$case_dir/worktree/.git"
install_dir="$case_dir/worktree"
cp "$case_dir/env.before" "$install_dir/.env"
run_update VERSION=v1
grep -q ' build$' "$GIT_UPDATE_TEST_LOG"

# Without local .git metadata, ordinary updates keep their previous behavior.
install_dir="$case_dir/archive"
mkdir -p "$install_dir"
git -C "$case_dir/seed" archive HEAD | tar -x -C "$install_dir"
cp "$case_dir/env.before" "$install_dir/.env"
run_update
grep -q ' build$' "$GIT_UPDATE_TEST_LOG"
if run_update VERSION=v1; then exit 1; fi
grep -q 'VERSION requires a Git checkout' "$case_dir/output.log"
test ! -s "$GIT_UPDATE_TEST_LOG"
mkdir "$install_dir/.git"
run_update
if run_update VERSION=v1; then exit 1; fi
grep -q 'Invalid .git metadata' "$case_dir/output.log"
test ! -s "$GIT_UPDATE_TEST_LOG"
echo 'PASS: Git update, tag/branch selection, worktrees, local changes and failure isolation'
