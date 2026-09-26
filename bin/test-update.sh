#!/usr/bin/env bash
# Exercise the real Make recipes with Docker replaced at the process boundary.
set -euo pipefail
repo_dir=$(cd "$(dirname "$0")/.." && pwd)
case_dir=$(mktemp -d)
trap 'rm -rf "$case_dir"' EXIT
cp "$repo_dir/Makefile" "$case_dir/Makefile"
mkdir -p "$case_dir/bin"
cp "$repo_dir/bin/"{start,update-source,init-data-volume,uninstall,refresh-documentation,documentation}.sh "$case_dir/bin/"
cp -R "$repo_dir/tooling" "$case_dir/tooling"
for script in update-secrets init-search-config update-release finalize-internal-secrets; do
    printf '#!/usr/bin/env bash\nexit 0\n' > "$case_dir/bin/$script.sh"
done
cat > "$case_dir/bin/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$UPDATE_TEST_LOG"
printf '%s\n' "${APP_ENV-unset}" >> "$UPDATE_TEST_LOG.env"
# Offline documentation commands must never run the application entrypoint.
if [[ " $* " == *" run "* ]] && [[ "$*" == *project_context.py* || "$*" == *architecture_check.py* || "$*" == *"app.documentation "* ]]; then
    [[ " $* " == *" --entrypoint python "* ]] || { echo 'Documentation would start the application entrypoint' >&2; exit 1; }
fi
# Generated files belong to the operator, not the image's runtime user.
if [[ "$*" == *project_context.py* || "$*" == *navigation-context.mjs* ]] && [[ " $* " != *" --check "* ]]; then
    [[ " $* " == *" --user $(id -u):$(id -g) "* ]] || { echo 'Generated documentation would use the image user' >&2; exit 1; }
fi
case " $* " in
    *"project_context.py --root /repo"*|*"navigation-context.mjs --root /repo"*)
        if [[ " $* " == *" --output /output "* ]]; then
            for arg in "$@"; do
                if [[ "$arg" == type=bind,src=*,dst=/output ]]; then output=${arg#type=bind,src=}; output=${output%,dst=/output}; fi
            done
            if [[ "$*" == *project_context.py* ]]; then name=project-map; else name=navigation; fi
            for locale in fr en; do
                mkdir -p "$output/docs/$locale/architecture/generated"
                for extension in json md; do printf 'synthetic output\n' > "$output/docs/$locale/architecture/generated/$name.$extension"; done
            done
        fi
        if [[ "${UPDATE_TEST_STALE_DOCS:-}" == 1 ]]; then
            if [[ "$*" == *project_context.py* ]]; then map=project; else map=navigation; fi
            if [[ " $* " == *" --check "* ]]; then
                test -f "$UPDATE_TEST_LOG.$map" || { echo "Stale $map documentation" >&2; exit 1; }
            else
                touch "$UPDATE_TEST_LOG.$map"
            fi
        fi
        ;;
    *" app.documentation revision "*)
        [[ "${UPDATE_TEST_FAILURE:-}" != documentation_revision ]] || exit 1
        printf '%064d\n' 1 ;;
    *" app.documentation refresh "*) [[ "${UPDATE_TEST_FAILURE:-}" != documentation ]] ;;
    *" app.documentation check "*) [[ "${UPDATE_TEST_FAILURE:-}" != documentation_sources ]] ;;
    *" config --services "*)
        [[ "${UPDATE_TEST_FAILURE:-}" != config ]] || exit 1
        printf '%s\n' backend frontend browser-secrets browser-executor search ssh-executor
        [[ " $* " != *compose.postgres.yaml* ]] || echo postgres
        [[ " $* " != *compose.turn.yaml* ]] || echo turn
        ;;
    *" ps --all --quiet "*)
        [[ "${UPDATE_TEST_FAILURE:-}" != query ]] || exit 1
        service=${@: -1}
        if [[ "${UPDATE_TEST_STACK:-missing}" != missing ]] && \
            [[ "${UPDATE_TEST_STACK:-}" != partial || "$service" != frontend ]]; then
            echo "container-$service"
        fi
        ;;
    *" ps --quiet "*)
        [[ "${UPDATE_TEST_FAILURE:-}" != port_query ]] || exit 1
        if [[ -n "${INSTALL_TEST_DOCKER_PORTS:-}" ]]; then echo port-container; fi
        ;;
    *" inspect --format "*)
        [[ "${UPDATE_TEST_FAILURE:-}" != inspect ]] || exit 1
        if [[ "$*" == *NetworkSettings.Ports* ]]; then
            printf '%s\n' "${INSTALL_TEST_DOCKER_PORTS:-}"
            exit 0
        fi
        service=${@: -1}
        if [[ "$service" == container-browser-secrets ]]; then
            echo 'exited|0|false||False'
        elif [[ "$service" != container-backend ]]; then
            echo 'running|0|false|healthy|False'
        else
            case "${UPDATE_TEST_STACK:-}" in
                stopped) echo 'exited|0|false|unhealthy|False' ;;
                sigterm) echo 'exited|143|false||False' ;;
                killed) echo 'exited|137|false||False' ;;
                oom) echo 'exited|137|true||False' ;;
                failed) echo 'exited|1|false||False' ;;
                unhealthy) echo 'running|0|false|unhealthy|False' ;;
                restarting) echo 'restarting|1|false||False' ;;
                created) echo 'created|0|false||False' ;;
                starting) echo 'running|0|false|starting|False' ;;
                oneoff) echo 'running|0|false|healthy|True' ;;
                *) echo 'running|0|false|healthy|False' ;;
            esac
        fi
        ;;
    *" ps -aq "*"service=postgres"*) printf '%s' "${UPDATE_TEST_POSTGRES_CONTAINER:-}" ;;
    *" ps -aq "*"service=turn"*) printf '%s' "${UPDATE_TEST_TURN_CONTAINER:-}" ;;
    *" compose version "*) [[ "${UPDATE_TEST_FAILURE:-}" != compose ]] ;;
    *" info "*) [[ "${UPDATE_TEST_FAILURE:-}" != daemon ]] ;;
    *" build "*)
        if [[ "$1" == build ]]; then
            [[ "${UPDATE_TEST_FAILURE:-}" != tooling_build ]]
        else
            [[ "${UPDATE_TEST_FAILURE:-}" != build ]]
        fi ;;
    *" down "*) [[ "${UPDATE_TEST_FAILURE:-}" != down ]] ;;
    *"chown app:app /data"*) [[ "${UPDATE_TEST_FAILURE:-}" != data_permissions ]] ;;
    *" rm --stop --force backend frontend "*) [[ "${UPDATE_TEST_FAILURE:-}" != reset ]] ;;
    *" up -d --no-build "*) [[ "${UPDATE_TEST_FAILURE:-}" != readiness && "${UPDATE_TEST_FAILURE:-}" != start ]] ;;
    *" --wait "*) [[ "${UPDATE_TEST_FAILURE:-}" != readiness ]] ;;
    *" core.params.internal_secrets "*) [[ "${UPDATE_TEST_FAILURE:-}" != secrets ]] ;;
esac
SH
chmod +x "$case_dir/bin/docker"
export PATH="$case_dir/bin:$PATH"
export UPDATE_TEST_LOG="$case_dir/docker.log"

run_update() {
    : > "$UPDATE_TEST_LOG"
    : > "$UPDATE_TEST_LOG.env"
    rm -f "$UPDATE_TEST_LOG.project" "$UPDATE_TEST_LOG.navigation"
    env -u APP_ENV -u RELEASE_DIR -u MAKEOVERRIDES MAKEFLAGS= make --no-print-directory -C "$case_dir" update \
        WEBRTC_TURN_MODE=disabled POSTGRES_MODE=embedded "$@" > "$case_dir/output.log" 2>&1
}

# Read APP_ENV from .env, just like a plain `make update` in a dev checkout.
printf 'APP_ENV=dev\n' > "$case_dir/.env"
run_update
grep -q -- '-f compose.dev.yaml build$' "$UPDATE_TEST_LOG"
# Recreate the API (DbAdmin on every update) and its proxy (backend DNS),
# while preserving unchanged infrastructure and waiting for service readiness.
grep -q ' rm --stop --force backend frontend$' "$UPDATE_TEST_LOG"
test "$(grep -c ' up ' "$UPDATE_TEST_LOG")" -eq 1
grep -q ' up -d --wait --wait-timeout 300$' "$UPDATE_TEST_LOG"
if grep -Eq ' (down|restart)( |$)' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: update stopped unchanged infrastructure' >&2
    exit 1
fi

for app_mode in prod preprod pp test demo custom DEV ''; do
    run_update APP_ENV="$app_mode"
    grep -q ' pull$' "$UPDATE_TEST_LOG"
    # Routine updates must reuse unchanged image layers while refreshing bases.
    grep -q ' build --pull$' "$UPDATE_TEST_LOG"
    test "$(sort -u "$UPDATE_TEST_LOG.env")" = "$app_mode"
    if grep -q 'compose.dev.yaml' "$UPDATE_TEST_LOG"; then
        echo 'FAIL: production update selected development configuration' >&2
        exit 1
    fi
done

# Stale generated docs are repaired automatically before building in both modes.
# Docker is the only substituted boundary; the real Make targets orchestrate the update.
for app_mode in dev prod; do
    UPDATE_TEST_STALE_DOCS=1 run_update APP_ENV="$app_mode"
    test -f "$UPDATE_TEST_LOG.project"
    test -f "$UPDATE_TEST_LOG.navigation"
    awk '
        /project_context.py --root \/repo --output \/output$/ { project = NR }
        /navigation-context.mjs --root \/repo --output \/output$/ { navigation = NR }
        / build( --pull)?$/ { build = NR }
        / up -d --wait / { ready = NR }
        /app.documentation refresh --expected-revision/ { refresh = NR }
        END { exit !(project && navigation && build > project && build > navigation && ready > build && refresh > ready) }
    ' "$UPDATE_TEST_LOG"
done

for app_mode in dev prod; do
    for failure in build data_permissions reset readiness documentation documentation_sources documentation_revision; do
        export UPDATE_TEST_FAILURE="$failure"
        if run_update APP_ENV="$app_mode"; then
            echo "FAIL: $app_mode update hid a $failure failure" >&2
            exit 1
        fi
        if [[ "$failure" == build || "$failure" == data_permissions || "$failure" == documentation_sources ]]; then
            # A failed build must leave the currently running application alone.
            if grep -Eq ' (down|up|rm|stop)( |$)' "$UPDATE_TEST_LOG"; then
                echo "FAIL: $app_mode update restarted after a failed build" >&2
                exit 1
            fi
        elif [[ "$failure" == reset ]]; then
            if grep -q ' up ' "$UPDATE_TEST_LOG"; then
                echo 'FAIL: update started services after a failed backend reset' >&2
                exit 1
            fi
        elif [[ "$failure" == readiness ]]; then
            grep -q ' logs --tail=200$' "$UPDATE_TEST_LOG"
        elif grep -q 'Update complete' "$case_dir/output.log"; then
            echo 'FAIL: update reported success with unavailable documentation' >&2
            exit 1
        fi
    done
done
unset UPDATE_TEST_FAILURE

# The documentation-only workflow never recreates services or grants new capabilities.
: > "$UPDATE_TEST_LOG"
env -u MAKEOVERRIDES MAKEFLAGS= make --no-print-directory -C "$case_dir" docs-update APP_ENV=dev \
    WEBRTC_TURN_MODE=disabled POSTGRES_MODE=embedded > "$case_dir/output.log" 2>&1
grep -q 'app.documentation refresh --expected-revision' "$UPDATE_TEST_LOG"
if grep -Eq ' (up|stop|rm|restart)( |$)' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: documentation refresh disrupted application services' >&2
    exit 1
fi
for app_mode in prod test ''; do
    : > "$UPDATE_TEST_LOG"
    if env -u MAKEOVERRIDES MAKEFLAGS= make --no-print-directory -C "$case_dir" docs-update APP_ENV="$app_mode" \
        > "$case_dir/output.log" 2>&1; then
        echo 'FAIL: documentation-only update bypassed the production release path' >&2
        exit 1
    fi
    test ! -s "$UPDATE_TEST_LOG"
done

for args in RELEASE_DIR=/unused-release; do
    if run_update "$args"; then
        echo "FAIL: update accepted $args in development" >&2
        exit 1
    fi
    test ! -s "$UPDATE_TEST_LOG"
done
# Missing APP_ENV defaults to production, including in child Make invocations.
: > "$case_dir/.env"
run_update
grep -q ' build --pull$' "$UPDATE_TEST_LOG"
grep -q 'Update complete (prod)' "$case_dir/output.log"

# An explicit shell environment wins over .env and reaches Docker.
printf 'APP_ENV=prod\n' > "$case_dir/.env"
: > "$UPDATE_TEST_LOG"
env -u MAKEOVERRIDES MAKEFLAGS= APP_ENV=dev make --no-print-directory -C "$case_dir" update \
    WEBRTC_TURN_MODE=disabled POSTGRES_MODE=embedded > "$case_dir/output.log" 2>&1
grep -q -- '-f compose.dev.yaml build$' "$UPDATE_TEST_LOG"

# An explicitly empty label also overrides .env and never enables development.
: > "$UPDATE_TEST_LOG"
env -u MAKEOVERRIDES MAKEFLAGS= APP_ENV= make --no-print-directory -C "$case_dir" update \
    WEBRTC_TURN_MODE=disabled POSTGRES_MODE=embedded > "$case_dir/output.log" 2>&1
grep -q ' build --pull$' "$UPDATE_TEST_LOG"
echo 'PASS: dev/prod updates, build/readiness failures and environment guards'

# Starting from a prepared checkout must refresh stale images before touching
# containers and report readiness failures instead of claiming startup succeeded.
for app_mode in dev prod demo; do
    printf 'APP_ENV=%s\nWEBRTC_TURN_MODE=disabled\n' "$app_mode" > "$case_dir/.env"
    for failure in none build readiness; do
        : > "$UPDATE_TEST_LOG"
        if UPDATE_TEST_FAILURE="$failure" env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
            make --no-print-directory -C "$case_dir" start > "$case_dir/output.log" 2>&1; then
            test "$failure" = none
        else
            test "$failure" != none
        fi
        if ! grep -q ' build' "$UPDATE_TEST_LOG"; then
            echo 'FAIL: start reused potentially stale images without building current sources' >&2
            exit 1
        fi
        if [[ "$failure" == build ]]; then
            if grep -Eq ' (down|up|rm|stop)( |$)' "$UPDATE_TEST_LOG"; then
                echo 'FAIL: start changed containers after a failed build' >&2
                exit 1
            fi
        else
            grep -q ' up -d --wait --wait-timeout 300$' "$UPDATE_TEST_LOG"
            if [[ "$failure" == readiness ]]; then
                grep -q ' logs --tail=200$' "$UPDATE_TEST_LOG"
            fi
        fi
    done
done
echo 'PASS: start rebuilds current sources and propagates build/readiness failures'

# Healthy or intentionally stopped containers are reused, including a completed initializer.
for stack in healthy stopped sigterm killed starting; do
    : > "$UPDATE_TEST_LOG"
    UPDATE_TEST_STACK="$stack" env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$case_dir" start > "$case_dir/output.log" 2>&1
    grep -q ' up -d --no-build --no-recreate --pull never --wait --wait-timeout 300$' "$UPDATE_TEST_LOG"
    if grep -Eq ' (build|pull|rm|down)( |$)| up -d --wait' "$UPDATE_TEST_LOG"; then
        echo "FAIL: start rebuilt or recreated an existing $stack stack" >&2
        exit 1
    fi
done
for stack in partial unhealthy restarting failed oom created oneoff; do
    : > "$UPDATE_TEST_LOG"
    UPDATE_TEST_STACK="$stack" env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$case_dir" start > "$case_dir/output.log" 2>&1
    test "$(grep -c ' build' "$UPDATE_TEST_LOG")" -eq 1
    grep -q ' up -d --wait --wait-timeout 300$' "$UPDATE_TEST_LOG"
done
# A failed existing-container start gets one update attempt, never a recursive loop.
for failure in start readiness; do
    : > "$UPDATE_TEST_LOG"
    if UPDATE_TEST_STACK=healthy UPDATE_TEST_FAILURE="$failure" env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$case_dir" start > "$case_dir/output.log" 2>&1; then
        test "$failure" = start
    else
        test "$failure" = readiness
    fi
    test "$(grep -c ' build' "$UPDATE_TEST_LOG")" -eq 1
done
# Docker/configuration query errors must not be mistaken for absent containers.
for failure in config query inspect; do
    : > "$UPDATE_TEST_LOG"
    if UPDATE_TEST_STACK=healthy UPDATE_TEST_FAILURE="$failure" env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$case_dir" start > "$case_dir/output.log" 2>&1; then
        echo "FAIL: start ignored $failure failure" >&2
        exit 1
    fi
    if grep -Eq ' (build|pull|up|start|rm|down)( |$)' "$UPDATE_TEST_LOG"; then
        echo 'FAIL: start mutated containers after a failed inspection' >&2
        exit 1
    fi
done
: > "$UPDATE_TEST_LOG"
UPDATE_TEST_STACK=stopped env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
    make --no-print-directory -C "$case_dir" restart > "$case_dir/output.log" 2>&1
grep -q ' stop$' "$UPDATE_TEST_LOG"
grep -q ' up -d --no-build --no-recreate --pull never --wait --wait-timeout 300$' "$UPDATE_TEST_LOG"
if grep -Eq ' (build|pull|rm|down)( |$)| up -d --wait' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: restart rebuilt or removed existing containers' >&2
    exit 1
fi
: > "$UPDATE_TEST_LOG"
env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
    make --no-print-directory -C "$case_dir" build > "$case_dir/output.log" 2>&1
grep -q ' build$' "$UPDATE_TEST_LOG"
if grep -Eq ' (up|start|stop|rm|down)( |$)' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: build changed containers' >&2
    exit 1
fi
echo 'PASS: start recovery, simple stop/start, standalone build and inspection failures'

: > "$UPDATE_TEST_LOG"
env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
    make --no-print-directory -C "$case_dir" uninstall </dev/null > "$case_dir/output.log" 2>&1
grep -q ' down$' "$UPDATE_TEST_LOG"
test -f "$case_dir/.env"
if grep -Eq ' --volumes| -v( |$)|volume rm' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: uninstall deleted persistent volumes' >&2
    exit 1
fi
# Volume deletion requires an explicit answer; defaults and invalid/partial input
# must never turn an unattended uninstall into a purge.
printf '# Preserve operator configuration\n' > "$case_dir/compose.override.yaml"
cp "$case_dir/.env" "$case_dir/env.before"
cp "$case_dir/compose.override.yaml" "$case_dir/override.before"
for answer in '' no non n yes oui y o YES OUI 'invalid\nnon' 'invalid\noui'; do
    : > "$UPDATE_TEST_LOG"
    printf '%b\n' "$answer" | env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$case_dir" uninstall > "$case_dir/output.log" 2>&1
    case "$answer" in
        yes|oui|y|o|YES|OUI|'invalid\noui') grep -q ' down --volumes$' "$UPDATE_TEST_LOG" ;;
        *)
            grep -q ' down$' "$UPDATE_TEST_LOG"
            ! grep -Eq ' --volumes| -v( |$)|volume rm' "$UPDATE_TEST_LOG"
            ;;
    esac
    test "$(grep -c ' down' "$UPDATE_TEST_LOG")" -eq 1
    cmp "$case_dir/env.before" "$case_dir/.env"
    cmp "$case_dir/override.before" "$case_dir/compose.override.yaml"
done
for volumes in no yes; do
    for images in no yes; do
        for orphans in no yes; do
            : > "$UPDATE_TEST_LOG"
            printf '%s\n' "$volumes" "$images" "$orphans" | env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
                make --no-print-directory -C "$case_dir" uninstall > "$case_dir/output.log" 2>&1
            expected=' down'
            [[ "$volumes" != yes ]] || expected+=' --volumes'
            [[ "$images" != yes ]] || expected+=' --rmi local'
            [[ "$orphans" != yes ]] || expected+=' --remove-orphans'
            grep -q "$expected$" "$UPDATE_TEST_LOG"
            test "$(grep -c ' down' "$UPDATE_TEST_LOG")" -eq 1
            # No machine-wide purge or forced image deletion may escape the project.
            ! grep -Eq 'prune|image rm|volume rm|--force|--rmi all' "$UPDATE_TEST_LOG"
            cmp "$case_dir/env.before" "$case_dir/.env"
            cmp "$case_dir/override.before" "$case_dir/compose.override.yaml"
        done
    done
done
for answer in invalid yes; do
    : > "$UPDATE_TEST_LOG"
    # Unterminated input is not confirmation, including a partial affirmative.
    printf '%s' "$answer" | env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$case_dir" uninstall > "$case_dir/output.log" 2>&1
    grep -q ' down$' "$UPDATE_TEST_LOG"
    ! grep -Eq ' --volumes| -v( |$)|volume rm' "$UPDATE_TEST_LOG"
done
for answer in 'no\nno\nno' 'yes\nyes\nyes'; do
    : > "$UPDATE_TEST_LOG"
    if printf '%b\n' "$answer" | UPDATE_TEST_FAILURE=down env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$case_dir" uninstall > "$case_dir/output.log" 2>&1; then
        echo 'FAIL: uninstall hid a Docker removal failure' >&2
        exit 1
    fi
done
# FORCE accepts all three cleanup choices without reading stdin, in both modes.
# Docker is replaced by the test executable; no running stack is removed.
for app_mode in dev prod; do
    : > "$UPDATE_TEST_LOG"
    env -u MAKEOVERRIDES MAKEFLAGS= APP_ENV="$app_mode" \
        make --no-print-directory -C "$case_dir" uninstall FORCE </dev/null > "$case_dir/output.log" 2>&1
    grep -q ' down --volumes --rmi local --remove-orphans$' "$UPDATE_TEST_LOG"
    test "$(grep -c ' down' "$UPDATE_TEST_LOG")" -eq 1
    ! grep -Eq 'prune|image rm|volume rm|--force|--rmi all' "$UPDATE_TEST_LOG"
    cmp "$case_dir/env.before" "$case_dir/.env"
    cmp "$case_dir/override.before" "$case_dir/compose.override.yaml"
done
: > "$UPDATE_TEST_LOG"
if UPDATE_TEST_FAILURE=down env -u APP_ENV -u MAKEOVERRIDES MAKEFLAGS= \
    make --no-print-directory -C "$case_dir" uninstall FORCE </dev/null > "$case_dir/output.log" 2>&1; then
    echo 'FAIL: forced uninstall hid a Docker removal failure' >&2
    exit 1
fi
grep -q ' down --volumes --rmi local --remove-orphans$' "$UPDATE_TEST_LOG"
rm "$case_dir/compose.override.yaml"
echo 'PASS: uninstall confirms volumes, local Compose images and project orphans separately; preserves configuration and propagates failures'

# Every lifecycle command selects PostgreSQL from the same deployment switch.
for app_mode in dev prod; do
    for postgres_mode in embedded external default; do
        printf 'APP_ENV=%s\nWEBRTC_TURN_MODE=disabled\n' "$app_mode" > "$case_dir/.env"
        case "$postgres_mode" in
            default) ;;
            *) printf 'POSTGRES_MODE=%s\n' "$postgres_mode" >> "$case_dir/.env" ;;
        esac
        : > "$UPDATE_TEST_LOG"
        env -u APP_ENV -u POSTGRES_MODE -u RELEASE_DIR -u MAKEOVERRIDES MAKEFLAGS= \
            make --no-print-directory -C "$case_dir" start stop update status uninstall clean </dev/null > "$case_dir/output.log" 2>&1
        if [[ "$postgres_mode" == external ]]; then
            if grep -q 'compose.postgres.yaml' "$UPDATE_TEST_LOG"; then
                echo 'FAIL: external PostgreSQL loaded the embedded Compose file' >&2
                exit 1
            fi
        # Documentation generation uses an independent frontend-only tooling project.
        # The application's lifecycle commands must still select the same database.
        elif grep '^compose ' "$UPDATE_TEST_LOG" | grep ' -f compose.yaml' | grep -v 'compose.postgres.yaml'; then
            echo 'FAIL: embedded PostgreSQL was omitted from a lifecycle command' >&2
            exit 1
        fi
    done
done
# Switching to an external database removes only its old container, never volumes.
: > "$UPDATE_TEST_LOG"
UPDATE_TEST_POSTGRES_CONTAINER=0123456789ab run_update POSTGRES_MODE=external
grep -q '^ps -aq --filter label=com.docker.compose.project=galaris --filter label=com.docker.compose.service=postgres$' "$UPDATE_TEST_LOG"
grep -q '^stop 0123456789ab$' "$UPDATE_TEST_LOG"
grep -q '^rm 0123456789ab$' "$UPDATE_TEST_LOG"
# Bind mounts used by documentation checks are not volume deletion flags.
if grep -Eq -- '--remove-orphans|compose.postgres.yaml| down .*--volumes| down .*-v( |$)|volume rm' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: external update removed unrelated containers/volumes or loaded embedded PostgreSQL' >&2
    exit 1
fi
: > "$UPDATE_TEST_LOG"
for invalid_mode in invalid true false ''; do
    if run_update POSTGRES_MODE="$invalid_mode"; then
        echo 'FAIL: invalid PostgreSQL mode was accepted' >&2
        exit 1
    fi
    test ! -s "$UPDATE_TEST_LOG"
done
# A disabled TURN relay must not survive an update as an orphan container.
UPDATE_TEST_TURN_CONTAINER=abcdef012345 run_update WEBRTC_TURN_MODE=disabled
grep -q '^stop abcdef012345$' "$UPDATE_TEST_LOG"
grep -q '^rm abcdef012345$' "$UPDATE_TEST_LOG"
UPDATE_TEST_TURN_CONTAINER=abcdef012345 run_update WEBRTC_TURN_MODE=embedded
if grep -q '^stop abcdef012345$' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: update stopped the configured TURN service' >&2
    exit 1
fi
echo 'PASS: optional PostgreSQL in dev/prod, default inclusion and invalid configuration'

# First installation prepares configuration; start/update build and start services.
# Keep real initialization scripts and replace Docker/network discovery at their boundaries.
install_dir="$case_dir/install"
mkdir -p "$install_dir/bin" "$install_dir/resources"
cp "$repo_dir/Makefile" "$repo_dir/.env.example" "$repo_dir/compose.override.yaml.example" "$install_dir/"
cp "$repo_dir/bin/"{install,start,update-source,init-data-volume,update-secrets,init-search-config,finalize-internal-secrets,refresh-documentation,documentation}.sh "$install_dir/bin/"
cp -R "$repo_dir/tooling" "$install_dir/tooling"
cp -R "$repo_dir/resources/search" "$install_dir/resources/"
cat > "$case_dir/bin/ip" <<'SH'
#!/usr/bin/env bash
echo '1.1.1.1 via 192.0.2.1 dev eth0 src 192.0.2.2'
SH
chmod +x "$case_dir/bin/ip"
cat > "$case_dir/bin/ss" <<'SH'
#!/usr/bin/env bash
[[ "${UPDATE_TEST_FAILURE:-}" != sockets ]] || exit 1
for port in ${INSTALL_TEST_LISTEN_PORTS:-}; do
    if [[ "${@: -1}" == "sport = :$port" ]]; then
        printf 'LISTEN 0 128 [::]:%s [::]:*\n' "$port"
    fi
done
SH
chmod +x "$case_dir/bin/ss"
run_install_command() {
    env -u APP_ENV -u POSTGRES_MODE -u INSTALL_PORT -u RELEASE_DIR -u MAKEOVERRIDES MAKEFLAGS= \
        make --no-print-directory -C "$install_dir" "$@" > "$install_dir/output.log" 2>&1
}
for failure in compose daemon; do
    if UPDATE_TEST_FAILURE="$failure" run_install_command install; then
        echo "FAIL: install ignored an unavailable Docker prerequisite: $failure" >&2
        exit 1
    fi
    test ! -e "$install_dir/.env"
done
: > "$UPDATE_TEST_LOG"
run_install_command install </dev/null
test -f "$install_dir/.env"
grep -q '^POSTGRES_MODE=embedded$' "$install_dir/.env"
grep -q '^APP_HOST=http://localhost:8484$' "$install_dir/.env"
grep -q '"8484:8484"' "$install_dir/compose.override.yaml"
test -f "$install_dir/compose.override.yaml"
test -f "$install_dir/data/search/settings.yml"
for key in ENCRYPTION_MASTER_KEY POSTGRES_PASSWORD WEBRTC_TURN_SHARED_SECRET; do
    grep -qE "^${key}=.+" "$install_dir/.env"
done
for key in AUTH_SECRET_KEY AUTH_WEBHOOK_TOKEN BROWSER_EXECUTOR_TOKEN; do
    ! grep -qE "^${key}=" "$install_dir/.env"
done
if grep -Eq ' (build|pull|up|down)( |$)' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: install built or changed services before .env configuration' >&2
    exit 1
fi

# Reinstalling preserves operator choices, secrets and custom Compose/search configuration.
sed -i -e 's|^APP_HOST=.*|APP_HOST=https://galaris.example.org|' \
    -e 's/^#\?TZ=.*/TZ=Europe\/Paris/' -e 's/^DEV_HOST_USER_ID=.*/DEV_HOST_USER_ID=4242/' "$install_dir/.env"
sed -i 's/"8484:8484"/"8585:8484"/' "$install_dir/compose.override.yaml"
printf '\n# Operator customization\n' >> "$install_dir/compose.override.yaml"
printf '\n# Operator customization\n' >> "$install_dir/data/search/settings.yml"
cp "$install_dir/.env" "$install_dir/env.before"
cp "$install_dir/compose.override.yaml" "$install_dir/override.before"
cp "$install_dir/data/search/settings.yml" "$install_dir/search.before"
run_install_command install
cmp "$install_dir/env.before" "$install_dir/.env"
cmp "$install_dir/override.before" "$install_dir/compose.override.yaml"
cmp "$install_dir/search.before" "$install_dir/data/search/settings.yml"
mv "$install_dir/compose.override.yaml" "$install_dir/docker-compose.override.yaml"
run_install_command install
cmp "$install_dir/override.before" "$install_dir/compose.override.yaml"
test ! -e "$install_dir/docker-compose.override.yaml"
if grep -Eq ' (build|pull|up|down)( |$)' "$UPDATE_TEST_LOG"; then
    echo 'FAIL: reinstall changed running services' >&2
    exit 1
fi

for app_mode in prod dev demo; do
    for command in start update; do
        sed -i "s/^#\?APP_ENV=.*/APP_ENV=$app_mode/" "$install_dir/.env"
        cp "$install_dir/.env" "$install_dir/env.before"
        : > "$UPDATE_TEST_LOG"
        : > "$UPDATE_TEST_LOG.env"
        run_install_command "$command"
        cmp "$install_dir/env.before" "$install_dir/.env"
        cmp "$install_dir/override.before" "$install_dir/compose.override.yaml"
        grep -q 'Open https://galaris.example.org in your browser.' "$install_dir/output.log"
        grep -q 'compose.override.yaml' "$UPDATE_TEST_LOG"
        grep -q ' build' "$UPDATE_TEST_LOG"
        grep -q ' up -d --wait --wait-timeout 300$' "$UPDATE_TEST_LOG"
        test "$(sort -u "$UPDATE_TEST_LOG.env")" = "$app_mode"
        if [[ "$app_mode" == dev ]]; then
            grep -q 'compose.dev.yaml' "$UPDATE_TEST_LOG"
        elif grep -q 'compose.dev.yaml' "$UPDATE_TEST_LOG"; then
            echo 'FAIL: installation ignored the configured production mode' >&2
            exit 1
        fi
    done
done
# Cleanup is gated by durable verification and preserves every unrelated byte,
# especially the encryption master key already generated for this isolated fixture.
cp "$install_dir/.env" "$install_dir/without-legacy.env"
printf '\nAUTH_SECRET_KEY=legacy-test-signing-secret\nBROWSER_EXECUTOR_TOKEN=legacy-test-browser-secret\nAUTH_WEBHOOK_TOKEN=obsolete-test-webhook-secret\n' >> "$install_dir/.env"
printf 'WEB_PUSH_VAPID_PUBLIC_KEY=legacy-public\nWEB_PUSH_VAPID_PRIVATE_KEY=legacy-private\nWEB_PUSH_VAPID_SUBJECT=mailto:admin@example.test\nWEB_PUSH_DELAY_SECONDS=4\n' >> "$install_dir/.env"
printf 'LOGFIRE_TOKEN=legacy-external-token\n' >> "$install_dir/.env"
printf 'BROWSER_SESSION_TTL_SECONDS=180\nBROWSER_MAX_SESSIONS=48\n' >> "$install_dir/.env"
printf 'MESSENGER_MAX_INLINE_MB=8\nPYDANTIC_AI_BINARY_INPUT_MAX_BYTES=41943040\nWEB_CONCURRENCY=4\n#HEALTHCHECK_URL=http://old.example.test/health\n' >> "$install_dir/.env"
cp "$install_dir/.env" "$install_dir/with-legacy.env"
if UPDATE_TEST_FAILURE=secrets bash "$install_dir/bin/finalize-internal-secrets.sh" -f compose.yaml; then
    echo 'FAIL: cleanup ignored failed secret verification' >&2
    exit 1
fi
cmp "$install_dir/with-legacy.env" "$install_dir/.env"
bash "$install_dir/bin/finalize-internal-secrets.sh" -f compose.yaml
printf '\n' >> "$install_dir/without-legacy.env"
cmp "$install_dir/without-legacy.env" "$install_dir/.env"
rm "$install_dir/.env"
for command in start update; do
    : > "$UPDATE_TEST_LOG"
    if run_install_command "$command"; then
        echo "FAIL: $command accepted missing installation configuration" >&2
        exit 1
    fi
    test ! -s "$UPDATE_TEST_LOG"
    grep -q 'make install' "$install_dir/output.log"
done
echo 'PASS: install, edit .env/ports, start/update; secrets, custom configuration and legacy override preserved'

# The prompt accepts the default, yes/no and retries invalid answers.
for answer in '' yes oui no non 'invalid\nn'; do
    rm -f "$install_dir/.env"
    printf '%b\n' "$answer" | run_install_command install
    case "$answer" in
        ''|yes|oui) expected=embedded ;;
        *) expected=external ;;
    esac
    grep -q "^POSTGRES_MODE=$expected$" "$install_dir/.env"
done

# Automation can make the same choice without answering a question.
for postgres_mode in embedded external; do
    rm "$install_dir/.env"
    run_install_command install POSTGRES_MODE="$postgres_mode" </dev/null
    grep -q "^POSTGRES_MODE=$postgres_mode$" "$install_dir/.env"
done
cp "$install_dir/.env" "$install_dir/env.before"
run_install_command install POSTGRES_MODE=embedded </dev/null
cmp "$install_dir/env.before" "$install_dir/.env"

# Preserve existing external/embedded deployments without changing anything else.
for mode in embedded external; do
    sed -i "s/^POSTGRES_MODE=.*/POSTGRES_MODE=$mode/" "$install_dir/.env"
    cp "$install_dir/.env" "$install_dir/env.before"
    run_install_command install </dev/null
    cmp "$install_dir/env.before" "$install_dir/.env"
done
rm "$install_dir/.env"
if run_install_command install POSTGRES_MODE=invalid </dev/null; then
    echo 'FAIL: installation accepted an invalid PostgreSQL switch' >&2
    exit 1
fi
test ! -e "$install_dir/.env"
echo 'PASS: PostgreSQL installation choice, automation and reinstallation'

# Fresh installations ask for PostgreSQL first, then retry invalid or busy ports.
rm -f "$install_dir/.env" "$install_dir/compose.override.yaml"
printf '\ninvalid\n0\n65536\n8484\n8585\n' | \
    INSTALL_TEST_LISTEN_PORTS=8484 run_install_command install
grep -q '^POSTGRES_MODE=embedded$' "$install_dir/.env"
grep -q '^APP_HOST=http://localhost:8585$' "$install_dir/.env"
grep -q '"8585:8484"' "$install_dir/compose.override.yaml"
grep -q '8484.*already in use' "$install_dir/output.log"

# Docker-published ports also count, even when ss has no listener (NAT only).
rm "$install_dir/.env" "$install_dir/compose.override.yaml"
printf 'no\n8484\n8686\n' | INSTALL_TEST_DOCKER_PORTS=8484 run_install_command install
grep -q '^POSTGRES_MODE=external$' "$install_dir/.env"
grep -q '^APP_HOST=http://localhost:8686$' "$install_dir/.env"
grep -q '"8686:8484"' "$install_dir/compose.override.yaml"

# Explicit ports support unattended installation; failure/EOF never loops or writes partial config.
rm "$install_dir/.env" "$install_dir/compose.override.yaml"
run_install_command install POSTGRES_MODE=embedded INSTALL_PORT=8787 </dev/null
grep -q '^APP_HOST=http://localhost:8787$' "$install_dir/.env"
grep -q '"8787:8484"' "$install_dir/compose.override.yaml"
cp "$install_dir/.env" "$install_dir/env.before"
cp "$install_dir/compose.override.yaml" "$install_dir/override.before"
INSTALL_TEST_LISTEN_PORTS=8787 run_install_command install INSTALL_PORT=8989 </dev/null
cmp "$install_dir/env.before" "$install_dir/.env"
cmp "$install_dir/override.before" "$install_dir/compose.override.yaml"
rm "$install_dir/.env" "$install_dir/compose.override.yaml"
if INSTALL_TEST_LISTEN_PORTS=8484 run_install_command install </dev/null; then
    echo 'FAIL: install accepted a busy port on EOF' >&2
    exit 1
fi
test ! -e "$install_dir/.env"
test ! -e "$install_dir/compose.override.yaml"
for port in invalid 0 65536 999999999999999999999999; do
    if run_install_command install INSTALL_PORT="$port" </dev/null; then
        echo 'FAIL: install accepted an invalid explicit port' >&2
        exit 1
    fi
    test ! -e "$install_dir/.env"
done
for failure in sockets port_query; do
    if UPDATE_TEST_FAILURE="$failure" run_install_command install </dev/null; then
        echo 'FAIL: install ignored a port inspection failure' >&2
        exit 1
    fi
    test ! -e "$install_dir/.env"
done
echo 'PASS: default/custom ports, retries, Docker publication, EOF and configuration preservation'
