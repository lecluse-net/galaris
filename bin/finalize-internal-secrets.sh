#!/usr/bin/env bash
# Remove obsolete keys after verifying the generated internal secrets.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose "$@" run --rm --no-deps -T --entrypoint python backend -m core.params.internal_secrets
sed -E -i '/^[[:space:]]*(export[[:space:]]+)?(AUTH_SECRET_KEY|BROWSER_EXECUTOR_TOKEN|BROWSER_SESSION_TTL_SECONDS|BROWSER_MAX_SESSIONS|AUTH_WEBHOOK_TOKEN|WEB_PUSH_VAPID_PUBLIC_KEY|WEB_PUSH_VAPID_PRIVATE_KEY|WEB_PUSH_VAPID_SUBJECT|WEB_PUSH_DELAY_SECONDS|LOGFIRE_TOKEN)[[:space:]]*=/d' .env
sed -E -i '/^[[:space:]]*#?[[:space:]]*(export[[:space:]]+)?(MESSENGER_MAX_INLINE_MB|PYDANTIC_AI_BINARY_INPUT_MAX_BYTES|WEB_CONCURRENCY|HEALTHCHECK_URL)[[:space:]]*=/d' .env
echo 'Persistent secrets and preferences verified; obsolete deployment variables removed from .env.'
