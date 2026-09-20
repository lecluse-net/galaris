#!/usr/bin/env bash
# The SSH executor and backend share /data. Docker can populate a new volume
# from either image, so its root ownership must not depend on creation order.
set -euo pipefail
echo 'Preparing application data directory permissions...'
docker compose "$@" run --rm --no-deps -T --user 0:0 --entrypoint sh backend \
    -ec 'mkdir -p /data/.galaris-volume; chown app:app /data'
# Keep the volume nonempty: otherwise Docker can copy the SSH image's /data
# ownership back over it when creating the next container.
