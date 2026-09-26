#!/usr/bin/env bash
# Filesystem contracts with Docker replaced at its process boundary (no daemon required).
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/source/bin" "$work/tools"
cp "$repo/bin/documentation.sh" "$work/source/bin/"
cp -R "$repo/tooling" "$work/source/"
export DOC_TEST_ROOT="$work/source"
cat > "$work/tools/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == build ]]; then
  [[ -z "${DOC_TEST_BUILDS:-}" ]] || printf '%s\n' "$1" >> "$DOC_TEST_BUILDS"
  context=${@: -1}
  [[ ! -e "$context/back" && ! -e "$context/docs" ]]
  exit 0
fi
[[ " $* " == *' --network none '* && " $* " == *' --read-only '* && " $* " == *' --cap-drop=ALL '* ]]
snapshot= output=
for arg in "$@"; do
  case "$arg" in
    type=bind,src=*,dst=/repo,readonly) snapshot=${arg#type=bind,src=}; snapshot=${snapshot%,dst=/repo,readonly} ;;
    type=bind,src=*,dst=/output) output=${arg#type=bind,src=}; output=${output%,dst=/output} ;;
  esac
done
[[ -f "$snapshot/back/core/example.py" ]]
[[ ! -e "$snapshot/.env" && ! -e "$snapshot/.git/config" && ! -e "$snapshot/docs/private.pem" && ! -e "$snapshot/front/app/private.env" ]]
for source in docs/fr/asset.txt docs/en/asset.txt project/plans/example.json project/decisions/example.HTML; do
  [[ -f "$snapshot/$source" ]] || { echo "Missing documentation input: $source" >&2; exit 1; }
done
if [[ " $* " != *' --output /output '* ]]; then [[ -z "$output" ]]; exit 0; fi
[[ -n "$output" ]]
[[ "${DOC_TEST_MODE:-}" != failure ]] || exit 1
if [[ "$*" == *project_context.py* ]]; then name=project-map; else name=navigation; fi
for locale in fr en; do
  mkdir -p "$output/docs/$locale/architecture/generated"
  for extension in json md; do printf 'generated\n' > "$output/docs/$locale/architecture/generated/$name.$extension"; done
done
case "${DOC_TEST_MODE:-}" in
  extra) printf 'unexpected\n' > "$output/extra" ;;
  output-link) rm "$output/docs/fr/architecture/generated/$name.md"; ln -s /etc/passwd "$output/docs/fr/architecture/generated/$name.md" ;;
  concurrent) printf 'changed\n' > "$DOC_TEST_ROOT/back/core/example.py" ;;
esac
MOCK
chmod +x "$work/tools/docker"
export PATH="$work/tools:$PATH"
mkdir -p "$work/source/back/core" "$work/source/front/app" "$work/source/docs" "$work/source/.git"
printf 'synthetic source\n' > "$work/source/back/core/example.py"
for file in .env .git/config docs/private.pem front/app/private.env; do printf 'synthetic sentinel\n' > "$work/source/$file"; done
export DOC_TEST_BUILDS="$work/builds"
run() { bash "$work/source/bin/documentation.sh" "$@"; }
# Inventory reports the selected sources only: no image build, no execution.
[[ $(run inventory) == 'back/core/example.py' ]]
[[ ! -e "$DOC_TEST_BUILDS" ]]
# The offline snapshot must preserve corpus formats and assets checked for locale parity.
for source in docs/fr/asset.txt docs/en/asset.txt project/plans/example.json project/decisions/example.HTML; do
  mkdir -p "$work/source/$(dirname "$source")"
  printf 'synthetic documentation\n' > "$work/source/$source"
done
run generate
[[ $(stat -c %u "$work/source/docs/fr/architecture/generated/project-map.md") == "$(id -u)" ]]
run check
for mode in failure extra output-link concurrent; do
  if DOC_TEST_MODE=$mode run generate > "$work/error" 2>&1; then printf 'Unexpected success: %s\n' "$mode" >&2; exit 1; fi
  [[ $(< "$work/source/docs/fr/architecture/generated/project-map.md") == generated ]]
done
ln -s /etc/passwd "$work/source/back/core/linked.py"
if run generate > "$work/error" 2>&1; then exit 1; fi
rm "$work/source/back/core/linked.py"
mv "$work/source/docs/fr/architecture/generated" "$work/destination"
ln -s "$work/destination" "$work/source/docs/fr/architecture/generated"
if run generate > "$work/error" 2>&1; then exit 1; fi
printf 'PASS: filtered snapshots, read-only checks, ownership, failure preservation, concurrency and symlinks\n'
