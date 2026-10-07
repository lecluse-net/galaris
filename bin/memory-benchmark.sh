#!/usr/bin/env bash
# No application imports, environment files, database, network or writable sources.
set -euo pipefail
benchmark_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
benchmark_output="$benchmark_root/artifacts/memory-benchmark"
mkdir -p -- "$benchmark_output"
if [ "$#" -eq 0 ]; then
    set -- generate
fi
docker run --rm --pull never --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --mount "type=bind,src=$benchmark_root/back/scripts/memory_benchmark,dst=/tool/memory_benchmark,readonly" \
    --mount "type=bind,src=$benchmark_output,dst=/output" \
    --env PYTHONDONTWRITEBYTECODE=1 --workdir /tool \
    python:3.14-slim-trixie python -m memory_benchmark "$@"
