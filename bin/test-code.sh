#!/usr/bin/env bash
# Isolated filesystem/namespace/Git qualification, including a synthetic SSH forge.
set -euo pipefail
cd "$(dirname "$0")/.."
tag="galaris-code-tests-$$"
probe="galaris-code-process-probe-$$"
source_dir=$(mktemp -d "${TMPDIR:-/tmp}/galaris-code-tests.XXXXXX")
cleanup() {
  docker rm -f "$probe" >/dev/null 2>&1 || true
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
# Check the real Docker ps contract too: a permissive mock previously accepted
# '-eo comm', which Docker rejects because it needs PID to filter container rows.
docker run -d --name "$probe" --network none --read-only --pids-limit 32 --memory 64m \
  --entrypoint /usr/bin/tini "$tag" -- python3 -c 'import time; time.sleep(300)' >/dev/null
docker pause "$probe" >/dev/null
processes=$(docker top "$probe" -eo pid,comm)
printf '%s\n' "$processes" | awk 'NR == 1 { if ($1 != "PID") exit 1; next } { names[$2] = 1 } END { if (!names["tini"] || !names["python3"]) exit 1 }'
docker rm -f "$probe" >/dev/null
docker run --rm --network none --entrypoint python3 \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --security-opt systempaths=unconfined --cap-add SYS_ADMIN --cap-add NET_ADMIN \
  --mount "type=bind,src=$source_dir,dst=/opt/galaris-code,readonly" \
  -w /opt/galaris-code "$tag" -m unittest discover -s tests -v
