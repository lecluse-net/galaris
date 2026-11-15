#!/usr/bin/env bash
# Desktop tooling is isolated from the running Galaris installation.
set -euo pipefail
cd "$(dirname "$0")/.."
operation=${1:-test}
case "$operation" in install|test|build|package|package-windows) ;; *) echo 'Usage: desktop.sh install|test|build|package|package-windows' >&2; exit 2 ;; esac
mkdir -p artifacts/desktop
image=galaris-desktop-tooling:local
if [[ "$operation" == install ]]; then
  # Bootstrap/update the lock without requiring an existing lock to build the image.
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e ELECTRON_SKIP_BINARY_DOWNLOAD=1 \
    -v "$PWD/desktop:/workspace" -w /workspace node:24-bookworm-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03 npm install --package-lock-only --ignore-scripts
  exit
fi
docker build -t "$image" desktop
dependencies="galaris-desktop-deps-$(sha256sum desktop/package-lock.json | cut -c 1-16)"
run=(docker run --rm --init --shm-size=1g --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/desktop:/workspace/desktop" -v "$PWD/front:/workspace/front:ro" \
  -v "$PWD/LICENSE.md:/workspace/LICENSE.md:ro" \
  -v "$PWD/artifacts/desktop:/workspace/artifacts/desktop" \
  -v "$dependencies:/workspace/desktop/node_modules" -w /workspace/desktop)
# Refresh the dependency volume from the image, without installing on the host.
docker run --rm --user root -v "$dependencies:/dependencies" "$image" \
  sh -c 'if [ ! -f /dependencies/.galaris-ready ]; then cp -a /workspace/desktop/node_modules/. /dependencies/ && chown -R "$1:$2" /dependencies && touch /dependencies/.galaris-ready; fi' sh "$(id -u)" "$(id -g)"
case "$operation" in
  test) "${run[@]}" "$image" sh -c 'npm run build && npm test && xvfb-run -a npm run test:desktop' ;;
  build) "${run[@]}" "$image" npm run build ;;
  package)
    "${run[@]}" "$image" npm run package -- --linux --x64
    "${run[@]}" "$image" xvfb-run -a node tests/package-smoke.mjs
    ;;
  package-windows)
    "${run[@]}" "$image" npm run build
    "${run[@]}" -e HOME=/tmp/galaris-desktop-home -e WINEPREFIX=/tmp/galaris-desktop-home/.wine \
      electronuserland/builder:wine@sha256:f3a8d451994c881d0972e7b1846ee4d4fdc15eb41fc6b1f350b38cbf99ca90fe \
      sh -c 'mkdir -p "$HOME" && exec node_modules/.bin/electron-builder --config electron-builder.cjs --win --x64 --publish never'
    ;;
esac
