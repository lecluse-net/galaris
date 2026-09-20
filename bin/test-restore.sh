#!/usr/bin/env bash
# Never loads application Compose files or touches live volumes.
set -euo pipefail
cd "$(dirname "$0")/.."
restore_root=$(mktemp -d "${TMPDIR:-/tmp}/galaris-restore.XXXXXX")
chmod 700 "$restore_root"
compose=(docker compose -p "galaris-restore-$$" -f compose.test.yaml)
cleanup() {
  "${compose[@]}" down --remove-orphans --rmi local >/dev/null 2>&1 || true
  rm -rf "$restore_root"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$restore_root/source/data" "$restore_root/restored" "$restore_root/backup"
umask 077
rehearsal_started=$SECONDS
"${compose[@]}" up --detach --wait db-test
"${compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$restore_root/source/data:/data" -v "$restore_root/source:/restore" backend \
  bash -c 'python -m core.dbadmin synchronize --mode test >/tmp/restore-dbadmin.log && python tests/restore_probe.py seed'
# Exercise independent DB/file writers before taking the documented quiescence
# boundary. Await complete operations before pg_dump and the filesystem archive.
"${compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$restore_root/source/data:/data" -v "$restore_root/source:/restore" backend \
  python tests/restore_concurrency.py write > "$restore_root/writers.log" 2>&1 &
writer_pid=$!
deadline=$((SECONDS + 60))
until [[ -f "$restore_root/source/writer-0-ready" && -f "$restore_root/source/writer-1-ready" ]]; do
  if (( SECONDS >= deadline )) || ! kill -0 "$writer_pid" 2>/dev/null; then
    cat "$restore_root/writers.log" >&2
    exit 1
  fi
  sleep 0.2
done
touch "$restore_root/source/quiesce"
wait "$writer_pid"
cat "$restore_root/writers.log"
"${compose[@]}" exec -T db-test pg_dump -U testuser -d test_db --format=custom \
  > "$restore_root/backup/database.dump"
tar -czf "$restore_root/backup/files-and-keys.tar.gz" -C "$restore_root/source" .
(
  cd "$restore_root/backup"
  sha256sum database.dump files-and-keys.tar.gz > SHA256SUMS
  sha256sum --check SHA256SUMS
)
"${compose[@]}" exec -T db-test createdb -U testuser test_restored
"${compose[@]}" exec -T db-test pg_restore -U testuser -d test_restored \
  --exit-on-error --no-owner --no-acl < "$restore_root/backup/database.dump"
tar -xzf "$restore_root/backup/files-and-keys.tar.gz" -C "$restore_root/restored"
"${compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" -e POSTGRES_DB=test_restored \
  -v "$restore_root/restored/data:/data" -v "$restore_root/restored:/restore" backend python tests/restore_probe.py verify
"${compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" -e POSTGRES_DB=test_restored \
  -v "$restore_root/restored/data:/data" -v "$restore_root/restored:/restore" backend python tests/restore_concurrency.py verify
echo "Restore verified: PostgreSQL, persistent files, managed-runtime canaries and encryption master key. Rehearsal duration: $((SECONDS - rehearsal_started)) seconds."
