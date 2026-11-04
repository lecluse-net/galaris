#!/usr/bin/env bash
# Exercise the public Make commands with real Docker/PostgreSQL and synthetic data.
set -euo pipefail
cd "$(dirname "$0")/.."
backup_test_root=$(mktemp -d "${TMPDIR:-/tmp}/galaris-backup-test.XXXXXX")
backup_test_project="galaris-backup-test-$$"
build=(docker compose -p "$backup_test_project" -f "$PWD/compose.test.yaml")
compose=(docker compose -p "$backup_test_project" -f "$backup_test_root/compose.yaml")
cleanup() {
    local result=$?
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    docker image rm "$backup_test_project-backend" >/dev/null 2>&1 || true
    rm -rf "$backup_test_root"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"${build[@]}" build backend
mkdir -p "$backup_test_root/bin" "$backup_test_root/back/core" "$backup_test_root/data/files" "$backup_test_root/data/skills"
cp Makefile "$backup_test_root/"
cp bin/{backup,update-journal}.sh bin/redact-update-log.awk "$backup_test_root/bin/"
cp back/core/backup.py "$backup_test_root/back/core/"
cat > "$backup_test_root/.env" <<EOF
APP_ENV=prod
APP_NAME=$backup_test_project
POSTGRES_MODE=external
WEBRTC_TURN_MODE=disabled
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=testuser
POSTGRES_PASSWORD=synthetic-backup-test-password
POSTGRES_DB=test_db
ENCRYPTION_MASTER_KEY=synthetic-backup-encryption-key-0001
EOF
cat > "$backup_test_root/compose.yaml" <<EOF
name: $backup_test_project
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: testuser
      POSTGRES_PASSWORD: synthetic-backup-test-password
      POSTGRES_DB: test_db
    tmpfs: [/var/lib/postgresql/data]
    healthcheck:
      test: [CMD-SHELL, "pg_isready -U testuser -d test_db"]
      interval: 1s
      timeout: 5s
      retries: 30
  backend:
    image: $backup_test_project-backend
    entrypoint: [sleep, infinity]
    stop_grace_period: 1s
    env_file: [.env]
    volumes: [./data:/data]
    depends_on:
      postgres: {condition: service_healthy}
EOF
"${compose[@]}" up -d --no-build --wait
mkdir -p "$backup_test_root/artifacts"
if flock "$backup_test_root/artifacts/.maintenance.lock" \
    env -u APP_ENV -u FILE -u RELEASE_DIR make --no-print-directory -C "$backup_test_root" save; then
    echo 'A concurrent maintenance operation was accepted.' >&2; exit 1
fi
test -n "$("${compose[@]}" ps --status running --quiet backend)"
"${compose[@]}" exec -T postgres psql -U testuser -d test_db -v ON_ERROR_STOP=1 \
    -c "CREATE TABLE backup_probe(content text); INSERT INTO backup_probe VALUES ('original')"
printf 'original skill\n' > "$backup_test_root/data/skills/private"
printf 'rsync original\n' > "$backup_test_root/data/files/separate"
env -u APP_ENV -u FILE -u RELEASE_DIR make --no-print-directory -C "$backup_test_root" save
mapfile -t archives < <(find "$backup_test_root/artifacts/backups" -name 'galaris-*.tar.gz')
test "${#archives[@]}" -eq 1
archive=${archives[0]}
test "$(stat -c %a "$archive")" = 600
test "$(stat -c %u "$archive")" = "$(id -u)"
test -n "$("${compose[@]}" ps --status running --quiet backend)"
env -u APP_ENV -u RELEASE_DIR make --no-print-directory -C "$backup_test_root" save \
    KEEP_STOPPED=1 FILE="$backup_test_root/artifacts/backups/rsync-coordinated.tar.gz"
test -z "$("${compose[@]}" ps --status running --quiet backend)"
"${compose[@]}" start backend
"${compose[@]}" exec -T postgres psql -U testuser -d test_db -v ON_ERROR_STOP=1 \
    -c "UPDATE backup_probe SET content='later'; CREATE TABLE later_object(id integer)"
printf 'later skill\n' > "$backup_test_root/data/skills/private"
printf 'rsync later\n' > "$backup_test_root/data/files/separate"
printf 'invalid archive\n' > "$backup_test_root/invalid.tar.gz"
if env -u APP_ENV -u RELEASE_DIR make --no-print-directory -C "$backup_test_root" restore FILE="$backup_test_root/invalid.tar.gz"; then
    echo 'Invalid archive was accepted.' >&2; exit 1
fi
test -n "$("${compose[@]}" ps --status running --quiet backend)"
env -u APP_ENV -u FILE -u RELEASE_DIR make --no-print-directory -C "$backup_test_root" restore "$archive"
test -z "$("${compose[@]}" ps --status running --quiet backend)"
test "$("${compose[@]}" exec -T postgres psql -U testuser -d test_db -Atc 'SELECT content FROM backup_probe')" = original
test "$("${compose[@]}" exec -T postgres psql -U testuser -d test_db -Atc "SELECT to_regclass('later_object') IS NULL")" = t
test "$(cat "$backup_test_root/data/skills/private")" = 'original skill'
test "$(cat "$backup_test_root/data/files/separate")" = 'rsync later'
test "$(find "$backup_test_root/artifacts/backups" -name 'before-restore-*.tar.gz' | wc -l)" -eq 1
echo 'PASS: real make save/restore, failed preflight without downtime, DB/data replacement, recovery archive and rsync exclusion'
