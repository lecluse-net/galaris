#!/usr/bin/env bash
# Prove the offline documentation boundary with real containers and synthetic fixtures.
#
# The runner is copied from this checkout, but every source it analyses is synthetic:
# the generator entrypoints are replaced by hostile modules that attempt forbidden
# reads, writes and network connections, then emit the expected outputs. Nothing here
# touches the real repository, the application Compose stack or production.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
source_root="$work/repo"
mkdir -p "$source_root/bin" "$source_root/back/scripts" "$source_root/front/scripts" "$source_root/front/app" \
  "$source_root/back/core" "$source_root/docs"
cp "$repo/bin/documentation.sh" "$source_root/bin/"
cp -R "$repo/tooling" "$source_root/"

# Secrets and out-of-scope files the runner must never expose to analysed code.
for sentinel in .env .git/config .git/credentials docs/private.pem back/entrypoint.sh \
  harness_manager/secrets.txt artifacts/report.txt; do
  mkdir -p "$source_root/$(dirname "$sentinel")"
  printf 'synthetic sentinel\n' > "$source_root/$sentinel"
done
printf 'synthetic module\n' > "$source_root/back/core/example.py"
printf 'synthetic page\n' > "$source_root/front/app/index.vue"

# A hostile generator: every escape attempt must be blocked, and each attempt is
# reported on stdout so the assertions below inspect the real container result.
cat > "$source_root/back/scripts/project_context.py" <<'PROBE'
import argparse
import pathlib
import socket
import sys


def attempt(name, action):
    try:
        action()
    except Exception as error:  # noqa: BLE001 - the probe reports every confinement outcome
        print(f"BLOCKED {name}: {type(error).__name__}")
        return
    print(f"ALLOWED {name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root, output = args.root.resolve(), (args.output or args.root).resolve()
    for relative in (".env", ".git/config", "docs/private.pem", "back/entrypoint.sh", "harness_manager/secrets.txt"):
        attempt(f"read:{relative}", lambda r=relative: (root / r).read_text(encoding="utf-8"))
    print(f"LISTED back: {len(sorted((root / 'back').rglob('*')))} entries")
    attempt("write:source", lambda: (root / "back/scripts/pwned.py").write_text("pwned\n"))
    attempt("write:etc", lambda: pathlib.Path("/etc/pwned").write_text("pwned\n"))
    attempt("write:root", lambda: pathlib.Path("/repo").joinpath("pwned").write_text("pwned\n"))
    attempt("network", lambda: socket.create_connection(("1.1.1.1", 80), timeout=5))
    for locale in ("fr", "en"):
        directory = output / "docs" / locale / "architecture" / "generated"
        directory.mkdir(parents=True, exist_ok=True)
        for name in ("project-map.json", "project-map.md"):
            (directory / name).write_text('{"probe": true}\n', encoding="utf-8")
    print("generated project map")


if __name__ == "__main__":
    sys.exit(main())
PROBE

cat > "$source_root/front/scripts/navigation-context.mjs" <<'PROBE'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import process from 'node:process'

const probe = async (name, action) => {
  try { await action() } catch (error) { console.log(`BLOCKED ${name}: ${error.code ?? error.name}`); return }
  console.log(`ALLOWED ${name}`)
}
const index = process.argv.indexOf('--root')
const outputIndex = process.argv.indexOf('--output')
const root = path.resolve(index >= 0 ? process.argv[index + 1] : '.')
const output = outputIndex >= 0 ? path.resolve(process.argv[outputIndex + 1]) : root
for (const relative of ['.env', '.git/config', 'docs/private.pem', 'back/entrypoint.sh', 'harness_manager/secrets.txt']) {
  await probe(`read:${relative}`, () => fs.readFileSync(path.join(root, relative), 'utf8'))
}
await probe('write:source', () => fs.writeFileSync(path.join(root, 'front/scripts/pwned.mjs'), 'pwned\n'))
await probe('write:etc', () => fs.writeFileSync('/etc/pwned', 'pwned\n'))
await probe('write:image', () => fs.writeFileSync('/tooling/pwned', 'pwned\n'))
await probe('network', () => new Promise((resolve, reject) => {
  const socket = net.createConnection({ host: '1.1.1.1', port: 80, timeout: 5000 })
  socket.on('connect', () => { socket.destroy(); resolve() })
  socket.on('error', reject)
  socket.on('timeout', () => { socket.destroy(); reject(new Error('timeout')) })
}))
for (const lang of ['fr', 'en']) {
  const directory = path.join(output, 'docs', lang, 'architecture/generated')
  fs.mkdirSync(directory, { recursive: true })
  for (const name of ['navigation.json', 'navigation.md']) fs.writeFileSync(path.join(directory, name), '{"probe": true}\n')
}
console.log('generated navigation')
PROBE

cd "$source_root"
report="$work/report.txt"
if ! bash bin/documentation.sh generate > "$report" 2>&1; then
  cat "$report" >&2
  echo 'Confinement run failed unexpectedly.' >&2
  exit 1
fi
cat "$report"
if grep -q '^ALLOWED' "$report"; then
  grep '^ALLOWED' "$report" >&2
  echo 'The container reached a forbidden resource.' >&2
  exit 1
fi
# The snapshot exposes only selected sources: the two generator entrypoints and one module.
grep -q '^LISTED back: 4 entries$' "$report" || { grep '^LISTED' "$report" >&2; echo 'Unexpected snapshot contents under back/.' >&2; exit 1; }
attempts=$(grep -c '^BLOCKED' "$report")
# Nine probes per runtime; a silent probe count drop must fail rather than weaken the test.
[[ "$attempts" == 18 ]] || { echo "Expected 18 blocked probes, saw $attempts." >&2; exit 1; }
for locale in fr en; do
  for name in project-map.json project-map.md navigation.json navigation.md; do
    file="docs/$locale/architecture/generated/$name"
    [[ -f "$file" ]] || { echo "Missing published output: $file" >&2; exit 1; }
    [[ $(stat -c %u "$file") == "$(id -u)" ]] || { echo "Wrong owner: $file" >&2; exit 1; }
  done
done
for sentinel in .env .git/config docs/private.pem back/entrypoint.sh harness_manager/secrets.txt; do
  [[ -e "$sentinel" ]] || { echo "Sentinel vanished: $sentinel" >&2; exit 1; }
done
printf 'PASS: %s confinement probes blocked, outputs published offline and owned by the operator\n' "$attempts"
