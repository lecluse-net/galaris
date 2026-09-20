#!/usr/bin/env bash
# Rehearse previous-source -> candidate DbAdmin with nonempty application data.
set -euo pipefail
cd "$(dirname "$0")/.."
upgrade_root=$(mktemp -d "${TMPDIR:-/tmp}/galaris-upgrade.XXXXXX")
compose=(docker compose -p "galaris-upgrade-$$" -f compose.test.yaml)
cleanup() {
  "${compose[@]}" down --remove-orphans --rmi local >/dev/null 2>&1 || true
  rm -rf "$upgrade_root"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$upgrade_root/previous" "$upgrade_root/data" "$upgrade_root/restore"
if [[ -n "${UPGRADE_EVIDENCE_DIR:-}" ]]; then
  : "${UPGRADE_PREVIOUS_IMAGE:?Immutable previous image required for qualification}"
  : "${UPGRADE_CANDIDATE_IMAGE:?Immutable candidate image required for qualification}"
  UPGRADE_EVIDENCE_DIR=$(realpath "$UPGRADE_EVIDENCE_DIR")
fi
previous_compose=("${compose[@]}")
candidate_compose=("${compose[@]}")
if [[ -n "${UPGRADE_PREVIOUS_IMAGE:-}" ]]; then
  if [[ ! "$UPGRADE_PREVIOUS_IMAGE" =~ (@sha256:|^sha256:)[0-9a-f]{64}$ ]]; then
    echo "UPGRADE_PREVIOUS_IMAGE must identify immutable image content" >&2
    exit 2
  fi
  if ! docker image inspect "$UPGRADE_PREVIOUS_IMAGE" >/dev/null 2>&1; then
    docker pull "$UPGRADE_PREVIOUS_IMAGE"
  fi
  cat > "$upgrade_root/previous-image.yaml" <<EOF
services:
  backend:
    image: $UPGRADE_PREVIOUS_IMAGE
    build: !reset null
    volumes: !reset []
    working_dir: /app
    entrypoint: []
    environment:
      PYTHONPATH: /app
EOF
  previous_compose+=(-f "$upgrade_root/previous-image.yaml")
  previous_source=""
elif [[ -n "${UPGRADE_SOURCE:-}" ]]; then
  previous_source=$(realpath "$UPGRADE_SOURCE")
else
  previous_ref=$(git rev-parse --verify "${UPGRADE_FROM:?Set UPGRADE_PREVIOUS_IMAGE (release qualification) or UPGRADE_FROM (source regression only)}^{commit}")
  git archive "$previous_ref" | tar -x -C "$upgrade_root/previous"
  previous_source="$upgrade_root/previous"
fi
previous_mounts=()
if [[ -n "$previous_source" ]]; then
  test -f "$previous_source/back/modules.py"
  previous_mounts=(-v "$previous_source:/repo:ro")
fi
if [[ -n "${UPGRADE_CANDIDATE_IMAGE:-}" ]]; then
  candidate_id=$(docker image inspect --format '{{.Id}}' "$UPGRADE_CANDIDATE_IMAGE")
  cat > "$upgrade_root/candidate-image.yaml" <<EOF
services:
  backend:
    image: $candidate_id
    build: !reset null
    volumes: !reset []
    working_dir: /app
    entrypoint: []
    environment:
      PYTHONPATH: /app
EOF
  candidate_compose+=(-f "$upgrade_root/candidate-image.yaml")
fi
"${compose[@]}" up --detach --wait db-test
"${previous_compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" \
  "${previous_mounts[@]}" -v "$PWD/back/tests/restore_probe.py:/probe.py:ro" \
  -v "$upgrade_root/data:/data" -v "$upgrade_root/restore:/restore" backend \
  bash -c 'python -m core.dbadmin synchronize --mode test && python /probe.py seed'
"${compose[@]}" exec -T db-test pg_dump -U testuser -d test_db --format=custom > "$upgrade_root/before-upgrade.dump"
tar -czf "$upgrade_root/before-upgrade-files.tar.gz" -C "$upgrade_root" data restore
started=$SECONDS
"${candidate_compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/back/tests/restore_probe.py:/probe.py:ro" \
  -v "$upgrade_root/data:/data" -v "$upgrade_root/restore:/restore" backend \
  bash -c 'export ENCRYPTION_MASTER_KEY="$(cat /restore/keys/ENCRYPTION_MASTER_KEY)" AUTH_SECRET_KEY="$(cat /restore/keys/AUTH_SECRET_KEY)"; python -m core.dbadmin synchronize --mode test && python /probe.py verify && python -m core.dbadmin synchronize --mode test'
echo "Candidate upgrade and API verification: $((SECONDS - started)) seconds"
# Rollback is a coordinated restore of the old schema and old binary, never an
# assumption that an old binary can safely read an arbitrary contracted schema.
"${compose[@]}" exec -T db-test createdb -U testuser test_rollback
"${compose[@]}" exec -T db-test pg_restore -U testuser -d test_rollback --exit-on-error --no-owner --no-acl < "$upgrade_root/before-upgrade.dump"
mkdir "$upgrade_root/rollback"
tar -xzf "$upgrade_root/before-upgrade-files.tar.gz" -C "$upgrade_root/rollback"
"${previous_compose[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" -e POSTGRES_DB=test_rollback \
  "${previous_mounts[@]}" -v "$PWD/back/tests/restore_probe.py:/probe.py:ro" \
  -v "$upgrade_root/rollback/data:/data" -v "$upgrade_root/rollback/restore:/restore" backend \
  bash -c 'export ENCRYPTION_MASTER_KEY="$(cat /restore/keys/ENCRYPTION_MASTER_KEY)" AUTH_SECRET_KEY="$(cat /restore/keys/AUTH_SECRET_KEY)"; python /probe.py verify'
echo "Upgrade verified: populated previous schema, candidate convergence, document API and ACL, repeated synchronization, old-binary restore."
if [[ -n "${UPGRADE_EVIDENCE_DIR:-}" ]]; then
  previous_id=$(docker image inspect --format '{{.Id}}' "$UPGRADE_PREVIOUS_IMAGE")
  tests_sha256=$(sha256sum back/tests/restore_probe.py bin/test-upgrade.sh back/scripts/release_qualification.py | sha256sum | cut -d ' ' -f1)
  docker run --rm --network none --user "$(id -u):$(id -g)" --entrypoint python3 \
    -v "$PWD/back/scripts/release_qualification.py:/qualification.py:ro" \
    -v "$UPGRADE_EVIDENCE_DIR:/evidence" "$candidate_id" \
    /qualification.py record-upgrade /evidence --previous "$previous_id" --candidate "$candidate_id" \
    --tests-commit "$(git rev-parse HEAD)" --tests-sha256 "$tests_sha256"
fi
