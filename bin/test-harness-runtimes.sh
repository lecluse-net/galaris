#!/usr/bin/env bash
# Actual SDK/binary compatibility, with no production service or credential access.
set -euo pipefail
cd "$(dirname "$0")/.."
source_root=$PWD
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
report_dir="$source_root/artifacts/harness-runtimes"
mkdir -p "$report_dir"
report="$report_dir/summary.txt"
: > "$report"
failed=0
for runtime in codex claude_agent hermes deepseek_harness; do
  context="$temporary/$runtime"
  mkdir -p "$context"
  cp back/bridge/"$runtime"/default-agent/Dockerfile "$context/"
  build_args=()
  if [[ $runtime == codex || $runtime == claude_agent ]]; then
    cp back/bridge/"$runtime"/default-agent/requirements.txt "$context/"
    if [[ $runtime == codex ]]; then
      cp back/bridge/codex/default-agent/server.py "$context/"
    else
      cp back/bridge/claude_agent/default-agent/server.py.txt "$context/"
    fi
    cp back/bridge/"$runtime"/stream_trace.py "$context/"
  elif [[ $runtime == deepseek_harness ]]; then
    cp back/bridge/deepseek_harness/default-agent/cordis.yml "$context/"
    cp back/bridge/deepseek_harness/runtime_adapter.py "$context/"
    revision=$(sed -n 's/^_DSH_REF = "\([a-f0-9]*\)"$/\1/p' back/bridge/deepseek_harness/harness_provider.py)
    [[ $revision =~ ^[a-f0-9]{40}$ ]]
    build_args+=(--build-arg "DSH_REF=$revision")
  fi
  context_hash=$(tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner -cf - -C "$context" . | sha256sum | cut -d ' ' -f1)
  image="galaris-qualification/$runtime:${context_hash:0:16}"
  printf 'Building %s\n' "$runtime"
  if ! docker build "${build_args[@]}" -t "$image" "$context" > "$report_dir/$runtime-build.log" 2>&1; then
    printf 'FAIL %s build (see %s-build.log)\n' "$runtime" "$runtime" >> "$report"
    failed=1
    continue
  fi
  digest=$(docker image inspect "$image" --format '{{.Id}}')
  printf 'Testing %s %s\n' "$runtime" "$digest"
  if docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
      --read-only --memory 4g --cpus 2 --pids-limit 256 \
      --tmpfs /tmp:mode=1777 --tmpfs /root:mode=1777 --tmpfs /home:mode=1777 \
      --tmpfs /var/lib/codex:mode=1777 --tmpfs /workspace:mode=1777 \
      --tmpfs /sessions:mode=1777 --tmpfs /data:mode=1777 \
      --mount "type=bind,src=$source_root/back/scripts/qualify_harness_runtime.py,dst=/probe.py,readonly" \
      --entrypoint python "$image" /probe.py "$runtime" > "$report_dir/$runtime.log" 2>&1; then
    printf 'PASS %s %s source=%s\n' "$runtime" "$digest" "$context_hash" >> "$report"
  else
    printf 'FAIL %s %s (see %s.log)\n' "$runtime" "$digest" "$runtime" >> "$report"
    failed=1
  fi
done
cat "$report"
exit "$failed"
