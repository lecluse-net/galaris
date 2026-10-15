#!/usr/bin/env bash
# Isolated filesystem/namespace/Git qualification, including a synthetic SSH forge.
set -euo pipefail
cd "$(dirname "$0")/.."
tag="galaris-code-tests-$$"
source_dir=$(mktemp -d "${TMPDIR:-/tmp}/galaris-code-tests.XXXXXX")
cleanup() {
  docker image rm "$tag" >/dev/null 2>&1 || true
  rm -rf "$source_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cp -r code-executor/. "$source_dir/"
chmod 700 "$source_dir/extension"
chmod 600 "$source_dir/extension/"*
docker build --target qualification -t "$tag" "$source_dir"
docker run --rm --network none --entrypoint python3 \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --security-opt systempaths=unconfined --cap-add SYS_ADMIN --cap-add NET_ADMIN \
  --mount "type=bind,src=$source_dir,dst=/opt/galaris-code,readonly" \
  -w /opt/galaris-code "$tag" -m unittest discover -s tests -v
