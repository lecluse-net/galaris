#!/usr/bin/env bash
set -euo pipefail

# Shared script: checks and generates missing secret keys in .env
# Used by bin/install.sh and make update

# --- Preliminary check ---
if [ ! -f .env ]; then
    echo "⚠️  .env not found. Run 'make install' first."
    exit 1
fi

echo "🔑 Checking secret keys in .env..."

generate_secret() {
    local key_name="$1"
    local generator="$2"

    if grep -qE "^#?${key_name}=$" .env 2>/dev/null; then
        # Key exists but is empty (commented or not)
        local secret
        secret=$(eval "$generator")
        sed -i "s|^#\\?${key_name}=.*|${key_name}=${secret}|" .env
        echo "✅ ${key_name} generated"
    elif grep -qE "^#?${key_name}=" .env 2>/dev/null; then
        # Key exists and has a value: make sure it is not commented
        sed -i "s/^#${key_name}=/${key_name}=/" .env
        echo "ℹ️  ${key_name} already set"
    else
        # Key does not exist at all in .env
        local secret
        secret=$(eval "$generator")
        echo "${key_name}=${secret}" >> .env
        echo "✅ ${key_name} added and generated"
    fi
}

generate_secret "ENCRYPTION_MASTER_KEY" "openssl rand -base64 48"
generate_secret "POSTGRES_PASSWORD"     "openssl rand -hex 16"

set_env_value() {
    local key_name="$1"
    local value="$2"

    if grep -qE "^#?${key_name}=" .env 2>/dev/null; then
        sed -i "s|^#\\?${key_name}=.*|${key_name}=${value}|" .env
    else
        echo "${key_name}=${value}" >> .env
    fi
}

resolve_turn_relay_ip() {
    local configured
    local resolved

    configured=$(sed -n 's/^WEBRTC_TURN_RELAY_IP=//p' .env | tail -n 1)
    configured=${configured:-auto}
    if [ "${configured}" = "auto" ]; then
        resolved=$(ip -4 route get 1.1.1.1 2>/dev/null \
            | awk '{for (field = 1; field <= NF; field++) if ($field == "src") {print $(field + 1); exit}}')
        if [ -z "${resolved}" ]; then
            resolved=$(hostname -I 2>/dev/null | awk '{print $1}')
        fi
    else
        resolved=${configured}
    fi

    if ! [[ "${resolved}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
        echo "❌ WEBRTC_TURN_RELAY_IP did not resolve to an IPv4 address" >&2
        exit 1
    fi
    local octet
    local -a octets
    IFS='.' read -r -a octets <<< "${resolved}"
    for octet in "${octets[@]}"; do
        if ((10#${octet} > 255)); then
            echo "❌ WEBRTC_TURN_RELAY_IP contains an invalid IPv4 address" >&2
            exit 1
        fi
    done

    set_env_value "WEBRTC_TURN_RELAY_IP_RESOLVED" "${resolved}"
    echo "ℹ️  Embedded TURN relay address detected"
}

turn_mode=$(sed -n 's/^WEBRTC_TURN_MODE=//p' .env | tail -n 1)
if [ -z "${turn_mode}" ] || [ "${turn_mode}" = "embedded" ]; then
    generate_secret "WEBRTC_TURN_SHARED_SECRET" "openssl rand -hex 32"
    resolve_turn_relay_ip
elif [ "${turn_mode}" = "external" ] && grep -qE '^#?WEBRTC_TURN_SHARED_SECRET=$' .env; then
    echo "⚠️  WEBRTC_TURN_SHARED_SECRET must match the external coturn secret"
else
    echo "ℹ️  Embedded TURN secret generation skipped (${turn_mode})"
fi

echo "✅ Secret keys checked"
