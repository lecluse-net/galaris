#!/usr/bin/env bash
# Real read-only agent calls on synthetic sources; no application lifespan or messages.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
campaign="artifacts/document-rag-qualification/$(date -u +%Y%m%dT%H%M%SZ)-$$"
remote_report="/tmp/galaris-document-rag-$$.json"
mkdir -p "$campaign"
status=0
docker compose exec -T backend python -m scripts.qualify_document_rag "$remote_report" "$@" > "$campaign/run.log" 2>&1 || status=$?
if ! docker compose cp "backend:$remote_report" "$campaign/report.json" > /dev/null; then
    echo "Qualification report unavailable; inspect $campaign/run.log" >&2
    if [[ $status == 0 ]]; then status=1; fi
    exit "$status"
fi
echo "Document RAG qualification: $campaign/report.json"
exit "$status"
