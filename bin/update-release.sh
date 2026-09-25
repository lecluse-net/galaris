#!/usr/bin/env bash
# Called only by the production-like make update target; never rebuilds an artifact.
set -euo pipefail
cd "$(dirname "$0")/.."
release_directory=$(realpath "${1:?A tested release directory is required}")
shift
test -f "$release_directory/TESTED_IMAGE_IDS" || { echo "Release has no successful exact-image qualification" >&2; exit 2; }
cmp "$release_directory/IMAGE_IDS" "$release_directory/TESTED_IMAGE_IDS"
bash bin/load-release.sh "$release_directory"
candidate_id=$(awk '$2 ~ /^galaris-release-back:/ {print $1}' "$release_directory/IMAGE_IDS")
installed_container=$(docker compose "$@" ps -q backend)
installed_id=""
if [[ -n "$installed_container" ]]; then
  installed_id=$(docker inspect --format '{{.Image}}' "$installed_container")
fi
docker run --rm --network none --entrypoint python3 \
  -v "$PWD/back/scripts/release_qualification.py:/qualification.py:ro" \
  -v "$release_directory:/evidence:ro" "$candidate_id" \
  /qualification.py promote /evidence --installed "$installed_id"
expected_docs=$(docker run --rm --network none --entrypoint python \
  -e ENCRYPTION_MASTER_KEY=documentation-offline-check-key-0001 "$candidate_id" \
  -m app.documentation revision)
[[ "$expected_docs" =~ ^[0-9a-f]{64}$ ]] || { echo 'Invalid release documentation revision' >&2; exit 1; }
bash bin/init-data-volume.sh "$@" -f "$release_directory/compose.release.yaml"
docker compose "$@" -f "$release_directory/compose.release.yaml" up -d --no-build --pull never --wait --wait-timeout 300
while read -r expected_id image_tag; do
  case "$image_tag" in
    galaris-release-back:*) service=backend ;;
    galaris-release-front:*) service=frontend ;;
    galaris-release-browser-executor:*) service=browser-executor ;;
    galaris-release-ssh-executor:*) service=ssh-executor ;;
    *) continue ;;
  esac
  container=$(docker compose "$@" -f "$release_directory/compose.release.yaml" ps -q "$service")
  # Optional executor services may be disabled by the deployment's profiles.
  if [[ -n "$container" ]]; then
    test "$(docker inspect --format '{{.Image}}' "$container")" = "$expected_id"
  fi
done < "$release_directory/IMAGE_IDS"
bash bin/finalize-internal-secrets.sh "$@" -f "$release_directory/compose.release.yaml"
echo 'Updating the shared documentation search index from the deployed release...'
docker compose "$@" -f "$release_directory/compose.release.yaml" exec -T backend \
  python -m app.documentation refresh --expected-revision "$expected_docs"
