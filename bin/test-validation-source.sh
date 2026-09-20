#!/usr/bin/env bash
# Exercise snapshot fidelity with real Git and tar, without committing or using Docker.
set -euo pipefail
source "$(dirname "$0")/validation-source.sh"
case_dir=$(mktemp -d)
trap 'rm -rf "$case_dir"' EXIT
work="$case_dir/work"
git init --quiet "$work"
printf '.env\nartifacts/\n' > "$work/.gitignore"
printf 'before\n' > "$work/tracked.py"
printf 'removed\n' > "$work/deleted.py"
git -C "$work" add .
printf 'after\n' > "$work/tracked.py"
chmod g+w "$work/tracked.py"
rm "$work/deleted.py"
printf 'new\n' > "$work/new file.py"
printf 'SECRET=do-not-copy\n' > "$work/.env"
validation_archive "$work" "$case_dir/first.tar"
test "$(tar -xOf "$case_dir/first.tar" tracked.py)" = after
test "$(tar -xOf "$case_dir/first.tar" 'new file.py')" = new
test "$(tar -tf "$case_dir/first.tar" | wc -l)" -eq 3
validation_archive "$work" "$case_dir/second.tar"
cmp "$case_dir/first.tar" "$case_dir/second.tar"
chmod g-w "$work/tracked.py"
validation_archive "$work" "$case_dir/second.tar"
cmp "$case_dir/first.tar" "$case_dir/second.tar"
chmod u+x "$work/tracked.py"
validation_archive "$work" "$case_dir/second.tar"
if cmp -s "$case_dir/first.tar" "$case_dir/second.tar"; then
  echo 'FAIL: an executable-bit change must invalidate the result' >&2
  exit 1
fi
chmod u-x "$work/tracked.py"
printf 'changed during tests\n' > "$work/tracked.py"
validation_archive "$work" "$case_dir/second.tar"
if cmp -s "$case_dir/first.tar" "$case_dir/second.tar"; then
  echo 'FAIL: a source change must invalidate the result' >&2
  exit 1
fi
echo 'PASS: local edits, additions, deletions, secret exclusion and source changes'
