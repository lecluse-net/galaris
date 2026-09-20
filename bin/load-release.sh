#!/usr/bin/env bash
# Verify/load an artifact without restarting services or running schema changes.
set -euo pipefail
release_directory=$(realpath "${1:?Usage: load-release.sh RELEASE_DIRECTORY}")
cd "$release_directory"
sha256sum --check SHA256SUMS
gzip -dc images.tar.gz | docker load
while read -r expected_id image_tag; do
  actual_id=$(docker image inspect --format '{{.Id}}' "$image_tag")
  if [[ "$actual_id" != "$expected_id" ]]; then
    echo "Unexpected image identity: $image_tag" >&2
    exit 1
  fi
done < IMAGE_IDS
echo "Exact release images loaded; no service was restarted."
