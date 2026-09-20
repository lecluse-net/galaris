#!/usr/bin/env bash
# Qualify loaded immutable images, then bind the evidence to their identities.
set -euo pipefail
cd "$(dirname "$0")/.."
export RELEASE_DIR=$(realpath "${RELEASE_DIR:?RELEASE_DIR is required}")
bash bin/load-release.sh "$RELEASE_DIR"
candidate_id=$(awk '$2 ~ /^galaris-release-back:/ {print $1}' "$RELEASE_DIR/IMAGE_IDS")
qualification=(docker run --rm --network none --user "$(id -u):$(id -g)" --entrypoint python3
  -v "$PWD/back/scripts/release_qualification.py:/qualification.py:ro"
  -v "$RELEASE_DIR:/evidence" "$candidate_id" /qualification.py)
"${qualification[@]}" check-upgrade /evidence
bash bin/test-e2e.sh
while read -r image_id image_tag; do
  case "$image_tag" in
    galaris-release-browser-executor:*)
      docker run --rm --network none --init --entrypoint npm "$image_id" test ;;
    galaris-release-ssh-executor:*)
      docker run --rm --network none --user 0:0 --entrypoint python3 \
        -v "$PWD/ssh-executor/tests:/opt/galaris-executor/tests:ro" \
        "$image_id" -m unittest discover -s /opt/galaris-executor/tests -v ;;
  esac
  bash bin/security-check.sh image "$image_id"
done < "$RELEASE_DIR/IMAGE_IDS"
tests_sha256=$(sha256sum bin/test-release.sh bin/test-e2e.sh bin/security-check.sh back/scripts/release_qualification.py | sha256sum | cut -d ' ' -f1)
"${qualification[@]}" qualify /evidence --tests-commit "$(git rev-parse HEAD)" --tests-sha256 "$tests_sha256"
cp "$RELEASE_DIR/IMAGE_IDS" "$RELEASE_DIR/TESTED_IMAGE_IDS"
(
  cd "$RELEASE_DIR"
  sha256sum SOURCE_COMMIT IMAGE_IDS TESTED_IMAGE_IDS compose.release.yaml images.tar.gz MANAGED_HARNESSES UPGRADE_QUALIFICATION.json QUALIFICATION.json > SHA256SUMS
)
echo "The exact image identities passed browser workflows and security scans."
