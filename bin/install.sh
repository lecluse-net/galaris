#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Initial installation of Galaris..."

# --- Prerequisites check ---
echo "🔍 Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install it: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "❌ The Docker Compose plugin is missing. Install it before running make install."
    exit 1
fi

if ! command -v openssl &> /dev/null; then
    echo "❌ OpenSSL is missing. Install it before running make install."
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "❌ The Docker daemon does not seem to be running. Please start it."
    exit 1
fi

echo "✅ Prerequisites OK"
echo ""

port_available() {
    local port=$1 listeners containers published
    local -a container_ids
    listeners=$(ss -H -ltn "sport = :$port") || return 2
    [[ -z "$listeners" ]] || return 1
    # Docker may publish through NAT without a socket visible to ss.
    containers=$(docker ps --quiet) || return 2
    if [[ -n "$containers" ]]; then
        mapfile -t container_ids <<< "$containers"
        published=$(docker inspect --format '{{range $port, $bindings := .NetworkSettings.Ports}}{{if eq (index (split $port "/") 1) "tcp"}}{{range $bindings}}{{println .HostPort}}{{end}}{{end}}{{end}}' "${container_ids[@]}") || return 2
        if grep -Fxq "$port" <<< "$published"; then return 1; fi
    fi
    return 0
}

choose_port() {
    if ! command -v ss >/dev/null; then
        echo '❌ The ss command is required to check available ports. Install iproute2 first.' >&2
        exit 1
    fi
    local answer closed result
    while true; do
        answer=${INSTALL_PORT:-}
        closed=false
        if [[ -z "$answer" ]]; then
            read -r -p 'Frontend host port [8484]: ' answer || closed=true
        fi
        answer=${answer:-8484}
        if [[ "$answer" =~ ^[0-9]{1,5}$ ]] && ((10#$answer >= 1 && 10#$answer <= 65535)); then
            install_port=$((10#$answer))
            result=0
            port_available "$install_port" || result=$?
            case "$result" in
                0) echo "✅ TCP port $install_port is available"; return ;;
                1) echo "⚠️  TCP port $install_port is already in use. Choose another port." ;;
                *) echo '❌ Cannot inspect host or Docker ports; configuration was not created.' >&2; exit 1 ;;
            esac
        else
            echo 'Please enter a port number between 1 and 65535.'
        fi
        if [[ -n "${INSTALL_PORT:-}" || "$closed" == true ]]; then
            echo '❌ No usable port selected. Rerun make install or set INSTALL_PORT=<free-port>.' >&2
            exit 1
        fi
    done
}

# --- .env ---
install_port=''
if [ ! -f .env ]; then
    postgres_mode=${POSTGRES_MODE:-}
    if [ -z "$postgres_mode" ]; then
        while true; do
            answer=""
            read -r -p "Include PostgreSQL with this installation? [Y/n] " answer || true
            case "${answer,,}" in
                ""|y|yes|o|oui) postgres_mode=embedded; break ;;
                n|no|non) postgres_mode=external; break ;;
                *) echo "Please answer yes or no." ;;
            esac
        done
    fi
    case "$postgres_mode" in
        embedded|external) ;;
        *) echo "❌ POSTGRES_MODE must be 'embedded' or 'external'." >&2; exit 1 ;;
    esac
    if [[ ! -f compose.override.yaml && ! -f docker-compose.override.yaml ]]; then
        choose_port
    else
        echo 'ℹ️  Existing Compose override preserved; review APP_HOST and its frontend ports together.'
    fi
    echo "📄 Creating .env from .env.example..."
    cp .env.example .env
    # Initialize the host UID only for a new configuration; preserve operator choices.
    host_uid=$(id -u)
    sed -i "s/^#\?DEV_HOST_USER_ID=.*/DEV_HOST_USER_ID=${host_uid}/" .env
    sed -i "s/^#\?POSTGRES_MODE=.*/POSTGRES_MODE=${postgres_mode}/" .env
    if [[ -n "$install_port" ]]; then
        sed -i "s|^APP_HOST=.*|APP_HOST=http://localhost:${install_port}|" .env
    fi
    if [ "$postgres_mode" = external ]; then
        echo "ℹ️  Configure POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER and POSTGRES_PASSWORD in .env before make start."
    fi
    echo "✅ .env created"
else
    echo "⚠️  .env already exists, keeping existing file"
fi

# --- compose.override.yaml ---
if [ -f compose.override.yaml ]; then
    echo "⚠️  compose.override.yaml already exists, keeping existing file"
elif [ -f docker-compose.override.yaml ]; then
    echo "📄 Migrating docker-compose.override.yaml to compose.override.yaml..."
    mv docker-compose.override.yaml compose.override.yaml
    echo "✅ Existing override migrated to compose.override.yaml"
else
    echo "📄 Creating compose.override.yaml from example..."
    cp compose.override.yaml.example compose.override.yaml
    if [[ -n "$install_port" ]]; then
        sed -i "s/\"8484:8484\"/\"${install_port}:8484\"/" compose.override.yaml
        echo "ℹ️  Frontend address: http://localhost:${install_port}"
    fi
    echo "✅ compose.override.yaml created"
fi

# --- SearXNG config ---
bash bin/init-search-config.sh

# --- Secret keys generation ---
echo ""
bash bin/update-secrets.sh
