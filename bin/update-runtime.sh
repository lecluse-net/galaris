#!/usr/bin/env bash
# The source-build update path; preserve the order and fail at the first error.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${APP_ENV:-prod}" != dev ]]; then
    echo 'Source builds are reserved for APP_ENV=dev. Production requires make update RELEASE_DIR=<qualified-directory>.' >&2
    exit 2
fi
source bin/update-journal.sh
update_journal_start

update_stage secrets
bash bin/update-secrets.sh
update_stage search-configuration
bash bin/init-search-config.sh
update_stage pull
echo '📥 Pulling infrastructure images, including SearXNG...'
docker compose "$@" pull --ignore-buildable
update_stage build
echo '🔨 Rebuilding images with cache...'
if [[ "${APP_ENV:-prod}" == dev ]]; then
    docker compose "$@" build
else
    docker compose "$@" build --pull
fi
update_stage data-volume
bash bin/init-data-volume.sh "$@"
update_stage unused-services
for service in ${GALARIS_UNUSED_SERVICES:-}; do
    containers=$(docker ps -aq --filter "label=com.docker.compose.project=${APP_NAME:-galaris}" --filter "label=com.docker.compose.service=$service")
    if [[ -n "$containers" ]]; then
        # Docker emits one identifier per line; split only that controlled output.
        docker stop $containers
        docker rm $containers
    fi
done
update_stage backend-reset
docker compose "$@" rm --stop --force backend frontend
update_stage readiness
echo '⏳ Waiting for the backend schema/data synchronization to complete...'
update_journal_watch_backend "$@"
update_journal_command compose-readiness docker compose "$@" up -d --wait --wait-timeout 300
update_journal_collect_backend
update_stage finalize-secrets
bash bin/finalize-internal-secrets.sh "$@"
update_stage documentation
echo '📚 Updating the shared documentation search index...'
bash bin/refresh-documentation.sh "$@"
update_stage editors
echo 'Checking configured external code editors...'
docker compose "$@" exec -T backend python -m code_editor_update
