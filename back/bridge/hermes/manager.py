"""Manage Hermes instances, configuration, lifecycle, and file transport.

Usage:
    from bridge.hermes.manager import manager
    from app.agent import Agent

    agent = manager.get_agent(agent)
    await agent.start()
    await agent.write_file(".env", content)
    content = await agent.read_file("data/config.yaml")
"""

from dataclasses import dataclass, field
from typing import Any, Optional, cast
from pathlib import Path
from loguru import logger
import asyncio
import asyncssh
import copy
import httpx
import json
import math
import re
import secrets
import unicodedata
import yaml

from core.util import (
    as_dict,
    as_list,
    decrypt_mapping_values,
    deep_merge,
    get_encryption_service,
)
from bridge.harness import merge_compose_defaults
from core.i18n import render_prompt, t, tr
from core.params import runtime_settings
from core.params import Params, params_service
from app.agent import Agent
from app.llm import LLM, llm_provider_service, llm_service
from bridge.harness import manager as harness_manager

from . import config_service


def _decrypt(value: str) -> str:
    """Decrypt encrypted values and preserve legacy plain text."""
    enc = get_encryption_service()
    return enc.decrypt(value) if enc.is_encrypted(value) else value


def _message(key: str, **values: Any) -> str:
    """Render a default-language Hermes configuration error from synchronous code."""
    return render_prompt(t(f"hermes.errors.{key}"), **values)


# Import app.voice lazily only when voice integration is enabled.

_DEFAULT_AGENT_DIR = Path(__file__).parent / "default-agent"

# Defaults

_HERMES_VERSION = "0.21.3"
_HERMES_RELEASE = "v2026.9.14"
_HERMES_UPSTREAM_IMAGE = f"nousresearch/hermes-agent:{_HERMES_RELEASE}@sha256:99641e57ec762c59e54cb44aa6746b7fc68c18b3c5ddb088af54234c613d9294"
_HERMES_HARNESS_IMAGE = f"galaris/hermes-harness:{_HERMES_RELEASE}"

_DEFAULT_COMPOSE: dict[str, Any] = {
    "services": {
        "agent": {
            "build": {
                "context": ".",
                "dockerfile": "Dockerfile",
                "args": {
                    "HERMES_IMAGE": _HERMES_UPSTREAM_IMAGE,
                },
            },
            "image": _HERMES_HARNESS_IMAGE,
            "container_name": None,
            "restart": "unless-stopped",
            "command": "gateway run",
            "volumes": [
                "./data:/opt/data",
                "hermes-bin:/opt/hermes",
            ],
            "environment": [
                "API_SERVER_ENABLED=true",
                "API_SERVER_HOST=0.0.0.0",
                "API_SERVER_KEY=${API_SERVER_KEY:-api-key-value}",
                "API_SERVER_CORS_ORIGINS='*'",
                "HERMES_API_V1=true",
                "HERMES_DASHBOARD=${DASHBOARD:-1}",
                "GATEWAY_ALLOW_ALL_USERS=true",
            ],
        }
    },
    "volumes": {
        "hermes-bin": None
    },
}

_DEFAULT_DATA_ENV: dict[str, str] = {
    "TERMINAL_MODAL_IMAGE": "nikolaik/python-nodejs:python3.11-nodejs20",
    "TERMINAL_TIMEOUT": "60",
    "TERMINAL_LIFETIME_SECONDS": "300",
    "BROWSERBASE_PROXIES": "true",
    "BROWSERBASE_ADVANCED_STEALTH": "false",
    "BROWSER_SESSION_TIMEOUT": "300",
    "BROWSER_INACTIVITY_TIMEOUT": "120",
    "WEB_TOOLS_DEBUG": "false",
    "VISION_TOOLS_DEBUG": "false",
    "MOA_TOOLS_DEBUG": "false",
    "IMAGE_TOOLS_DEBUG": "false",
}

# LLM provider detection

# Providers natively supported by Hermes Agent. The first match wins; all others use custom.
_HERMES_PROVIDER_MAP: list[tuple[str, str, str | None]] = [
    ("openrouter.ai",                     "openrouter",   "OPENROUTER_API_KEY"),
    ("api.anthropic.com",                 "anthropic",    "ANTHROPIC_API_KEY"),
    ("api.githubcopilot.com",             "copilot",      "GITHUB_TOKEN"),
    ("generativelanguage.googleapis.com", "gemini",       "GOOGLE_API_KEY"),
    ("aistudio.google.com",               "gemini",       "GOOGLE_API_KEY"),
    ("api-inference.huggingface.co",      "huggingface",  "HF_TOKEN"),
    ("huggingface.co",                    "huggingface",  "HF_TOKEN"),
    ("integrate.api.nvidia.com",          "nvidia",       "NVIDIA_API_KEY"),
    ("build.nvidia.com",                  "nvidia",       "NVIDIA_API_KEY"),
    ("api.arcee.ai",                      "arcee",        "ARCEEAI_API_KEY"),
    ("api.moonshot.cn",                   "kimi-coding",  "KIMI_API_KEY"),
    ("api.kimi.ai",                       "kimi-coding",  "KIMI_API_KEY"),
    ("api.minimax.io",                    "minimax",      "MINIMAX_API_KEY"),
    ("api.minimax.cn",                    "minimax-cn",   "MINIMAX_CN_API_KEY"),
    ("api.z.ai",                          "zai",          "GLM_API_KEY"),
    ("zhipuai.cn",                        "zai",          "GLM_API_KEY"),
    ("ollama.com",                        "ollama-cloud", "OLLAMA_API_KEY"),
    ("kilocode.ai",                       "kilocode",     "KILOCODE_API_KEY"),
]

_GALARIS_LLM_KEY_ENV = "GALARIS_LLM_API_KEY"
_GALARIS_MEMORY_URL_ENV = "GALARIS_MEMORY_API_URL"
_GALARIS_MEMORY_TOKEN_ENV = "GALARIS_MEMORY_TOKEN"
_GALARIS_MEMORY_AGENT_ENV = "GALARIS_MEMORY_AGENT_ID"
_GALARIS_MEMORY_PLUGIN_KEY = "galaris-memory"
_GALARIS_MEMORY_TEMPLATE_PREFIX = "data/plugins/memory/galaris/"
_GALARIS_MEMORY_LEGACY_PREFIX = "data/plugins/galaris/"
_HERMES_NO_BUNDLED_SKILLS_MARKER = "data/.no-bundled-skills"
_GALARIS_BUNDLED_SKILLS_MARKER_CONTENT = (
    "Managed by Galaris: Hermes bundled skills are disabled.\n"
)
_LEGACY_GALARIS_MANAGED_DISABLED_SKILLS_KEY = "_galaris_managed_disabled"
_GALARIS_MANAGED_TERMINAL_KEY = "_galaris_managed_terminal"
_GALARIS_SSH_DIR = "data/.galaris/ssh"
_GALARIS_SSH_CONFIG_FIELDS = (
    "backend",
    "cwd",
    "timeout",
    "ssh_host",
    "ssh_user",
    "ssh_port",
    "ssh_key",
)
_HERMES_RUNTIME_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_GALARIS_BUILTIN_MEMORY_DEFAULTS: dict[str, Any] = {
    "memory": {
        "memory_enabled": False,
        "user_profile_enabled": False,
    },
}
# Shared marker key written inside the generated ``tts``/``stt`` blocks so a later
# sync can remove exactly what Galaris injected without touching user values.
_GALARIS_MANAGED_PROVIDER_KEY = "_galaris_managed_provider"
_HERMES_COMPRESSION_FLOOR = 64_000
_KANBAN_TASK_RE = re.compile(r"^t_[0-9a-f]{8}$")
_DIRECT_LLM_KEY_ENVS = {
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY",
    "CEREBRAS_API_KEY",
    "SAMBANOVA_API_KEY",
    "COHERE_API_KEY",
    "CUSTOM_API_KEY",
    "LM_API_KEY",
    *(key for _, _, key in _HERMES_PROVIDER_MAP if key),
}


@dataclass(frozen=True)
class _HermesSshConnection:
    """Decrypted external Console target, scoped to one Hermes sync."""

    connection_id: int
    host: str
    port: int
    username: str
    private_key: str = field(repr=False)
    private_key_passphrase: str | None = field(repr=False)
    known_host_key: str = field(repr=False)
    connect_timeout_s: float
    command_timeout_s: int


def _required_ssh_param(params: dict[str, Any], name: str) -> str:
    value = str(params.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Console SSH parameter is required: {name}")
    return value


def _ssh_identity_param(params: dict[str, Any], name: str) -> str:
    value = _required_ssh_param(params, name)
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise RuntimeError(f"Invalid Console SSH parameter: {name}")
    return value


def _bounded_ssh_number(
    params: dict[str, Any],
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = float(str(raw))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid Console SSH parameter: {name}") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise RuntimeError(f"Console SSH parameter is out of range: {name}")
    return value


async def _resolve_external_console_ssh(
    agent_id: int,
) -> _HermesSshConnection | None:
    """Resolve the active external Console through already allowed public domains."""

    from app.connection import connection_service
    from app.tools import tool_service

    for connection in await connection_service.get_connections_by_agent(agent_id):
        tool = await tool_service.get_tool_by_id(connection.tool_id)
        if tool is None or tool.code != "console" or not connection.active:
            continue
        _, params = await connection_service.get_params_as_dict(
            connection,
            decrypt_passwords=True,
        )
        host = _ssh_identity_param(params, "host")
        if host == "ssh-executor":
            return None
        return _HermesSshConnection(
            connection_id=connection.id,
            host=host,
            port=int(_bounded_ssh_number(params, "port", 22, 1, 65535)),
            username=_ssh_identity_param(params, "username"),
            private_key=_required_ssh_param(params, "private_key"),
            private_key_passphrase=(
                str(params["private_key_passphrase"])
                if params.get("private_key_passphrase")
                else None
            ),
            known_host_key=_required_ssh_param(params, "known_host_key"),
            connect_timeout_s=_bounded_ssh_number(
                params,
                "connect_timeout_s",
                10,
                1,
                120,
            ),
            command_timeout_s=math.ceil(_bounded_ssh_number(
                params,
                "command_timeout_s",
                300,
                1,
                86400,
            )),
        )
    return None


def _export_openssh_private_key(ssh: _HermesSshConnection) -> str:
    key = asyncssh.import_private_key(
        ssh.private_key,
        passphrase=ssh.private_key_passphrase,
    )
    return key.export_private_key().decode("ascii")


def _render_known_hosts(ssh: _HermesSshConnection) -> str:
    value = ssh.known_host_key.strip()
    first = value.split(maxsplit=1)[0] if value else ""
    if first.startswith(("ssh-", "ecdsa-", "sk-", "rsa-sha2-")):
        host = ssh.host if ssh.port == 22 else f"[{ssh.host}]:{ssh.port}"
        value = f"{host} {value}"
    return value.rstrip() + "\n"


def _detect_hermes_provider(base_url: str) -> tuple[str, Optional[str]]:  # pyright: ignore[reportUnusedFunction]
    """Return the Hermes provider name and optional API-key environment name."""
    lower = base_url.lower()
    if ":1234" in lower or "lmstudio" in lower:
        return "lmstudio", "LM_API_KEY"
    if ":11434" in lower:
        return "custom", "CUSTOM_API_KEY"
    for pattern, provider, key_env in _HERMES_PROVIDER_MAP:
        if pattern in lower:
            return provider, key_env
    return "custom", "CUSTOM_API_KEY"


async def _get_effective_llm(agent: Agent) -> Optional[LLM]:
    """Return the agent model or the default executor model."""
    return await llm_service.get_llm_for_agent(agent)


# Serialization

def _serialize_env(d: dict[str, str]) -> str:
    return "\n".join(f"{k}={v}" for k, v in d.items()) + "\n"


async def _load_global_data_env() -> dict[str, str]:
    """Load decrypted global Hermes data/.env values from a JSON parameter."""
    raw = await params_service.get(Params.HERMES_DEFAULT_DATA_ENV)
    if not raw:
        return {}
    try:
        data: object = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Ignoring unreadable JSON parameter {}", Params.HERMES_DEFAULT_DATA_ENV)
        return {}
    if not isinstance(data, dict):
        logger.warning("Ignoring non-object JSON parameter {}", Params.HERMES_DEFAULT_DATA_ENV)
        return {}
    typed = cast(dict[Any, Any], data)
    return {str(k): str(v) for k, v in typed.items()}


# Default configuration builders

def _default_env_dict(agent: Agent) -> dict[str, str]:
    """Build the Docker Compose .env mapping."""
    dashboard_enabled = agent.hermes_dashboard_enabled
    api_key = _decrypt(agent.hermes_api_key) if agent.hermes_api_key else "change-me"
    return {
        "API_SERVER_KEY": api_key,
        "DASHBOARD":      "1" if dashboard_enabled else "0",
    }

# Configuration injection

def _llm_gateway_url() -> str:
    api_url = runtime_settings.HARNESS_API_URL
    if not api_url:
        raise RuntimeError(_message("mcp_url_required"))
    return f"{api_url}/llm/openai"


def _compression_threshold(context_length: int) -> float:
    """Target Hermes' 64k floor without exceeding its default 50 percent threshold."""
    return round(
        min(0.50, _HERMES_COMPRESSION_FLOOR / max(context_length, 1)),
        6,
    )


def _llm_proxy_model(llm: LLM) -> str:
    """Return the stable model identifier exposed by the Galaris proxy."""
    code = str(getattr(llm, "code", "") or "").strip()
    return code or f"llm-{llm.id}"


def _inject_llm(
    config: dict[str, Any],
    data_env: dict[str, str],
    llm: LLM,
    token: str,
) -> None:
    """Force the primary Hermes model through the Galaris LLM proxy."""
    _raw_context = getattr(llm, "context_length", None)
    effective_context = _raw_context if isinstance(_raw_context, int) and _raw_context > 0 else 0
    has_context = effective_context > 0

    config.setdefault("model", {})
    config["model"].update({
        "default": _llm_proxy_model(llm),
        "provider": "custom",
        "base_url": _llm_gateway_url(),
        "api_key": f"${{{_GALARIS_LLM_KEY_ENV}}}",
        "api_mode": "chat_completions",
    })
    if has_context:
        config["model"]["context_length"] = effective_context

        # Threshold is a context-window ratio with an absolute Hermes 64k floor.
        compression = config.setdefault("compression", {})
        compression.update({
            "enabled": True,
            "threshold": _compression_threshold(effective_context),
            "target_ratio": 0.10,
            "protect_first_n": 0,
            "protect_last_n": 8,
            "abort_on_summary_failure": False,
        })

        # Hermes uses the primary model unless an auxiliary override exists.
        auxiliary_compression = config.setdefault("auxiliary", {}).setdefault("compression", {})
        if not auxiliary_compression.get("model"):
            auxiliary_compression["context_length"] = effective_context

    data_env[_GALARIS_LLM_KEY_ENV] = token


def _inject_vision_llm(config: dict[str, Any], data_env: dict[str, str], llm: LLM, token: str) -> None:
    """Inject an auxiliary vision model for a text-only primary Hermes model."""
    vision = config.setdefault("auxiliary", {}).setdefault("vision", {})
    vision.update({
        "provider": "custom",
        "model": _llm_proxy_model(llm),
        "base_url": _llm_gateway_url(),
        "api_key": f"${{{_GALARIS_LLM_KEY_ENV}}}",
    })
    data_env[_GALARIS_LLM_KEY_ENV] = token


def _remove_direct_llm_credentials(data_env: dict[str, str]) -> None:
    """Remove credentials that would allow Hermes to bypass Galaris."""
    for key in _DIRECT_LLM_KEY_ENVS:
        data_env.pop(key, None)


def _remove_direct_llm_compose_credentials(compose: dict[str, Any]) -> None:
    """Remove provider keys introduced by Docker Compose overrides."""
    services = compose.get("services")
    if not isinstance(services, dict):
        return
    for service_item in as_dict(services).values():
        service = as_dict(service_item)
        environment = service.get("environment")
        if isinstance(environment, dict):
            env_d = as_dict(environment)
            for key in _DIRECT_LLM_KEY_ENVS:
                env_d.pop(key, None)
        elif isinstance(environment, list):
            service["environment"] = [
                entry
                for entry in as_list(environment)
                if not (
                    isinstance(entry, str)
                    and entry.split("=", 1)[0].strip() in _DIRECT_LLM_KEY_ENVS
                )
            ]


def _remove_galaris_tts_injection(config: dict[str, Any]) -> None:
    """Remove only the TTS provider block previously generated by Galaris."""
    raw_tts = config.get("tts")
    if not isinstance(raw_tts, dict):
        return
    tts = as_dict(raw_tts)
    managed_provider = str(tts.pop(_GALARIS_MANAGED_PROVIDER_KEY, "") or "").strip()
    if not managed_provider:
        return
    if str(tts.get("provider") or "").strip() == managed_provider:
        tts.pop("provider", None)
    tts.pop(managed_provider, None)
    raw_providers = tts.get("providers")
    if isinstance(raw_providers, dict):
        providers = as_dict(raw_providers)
        providers.pop(managed_provider, None)
        if not providers:
            tts.pop("providers", None)
    if not tts:
        config.pop("tts", None)


def _remove_galaris_stt_injection(config: dict[str, Any]) -> None:
    """Remove only the STT provider block previously generated by Galaris."""
    raw_stt = config.get("stt")
    if not isinstance(raw_stt, dict):
        return
    stt = as_dict(raw_stt)
    managed_provider = str(stt.pop(_GALARIS_MANAGED_PROVIDER_KEY, "") or "").strip()
    if not managed_provider:
        return
    if str(stt.get("provider") or "").strip() == managed_provider:
        stt.pop("provider", None)
    stt.pop(managed_provider, None)
    if not stt:
        config.pop("stt", None)


def _voice_identifier(llm: LLM) -> str:
    """Return the provider voice identifier stored by resource discovery."""
    value = str(llm.llm_name or "").strip()
    return value.removeprefix("voice:")


def _require_tts_key(provider_name: str, api_key: str | None) -> str:
    if not api_key:
        raise RuntimeError(
            f"Le fournisseur TTS {provider_name} n'a pas de clé API configurée"
        )
    return api_key


def _command_tts_config(
    provider: str,
    voice: str,
    *,
    model: str = "",
) -> dict[str, Any]:
    model_arg = "--model {model} " if model else ""
    return {
        "type": "command",
        "command": (
            'python "${HERMES_HOME:-/opt/data}/scripts/galaris_tts.py" '
            f"--provider {provider} --voice {{voice}} "
            f"{model_arg}"
            "--input {input_path} --output {output_path}"
        ),
        "voice": voice,
        **({"model": model} if model else {}),
        "output_format": "mp3",
        "voice_compatible": True,
    }


async def _inject_tts(
    config: dict[str, Any],
    data_env: dict[str, str],
    agent: Agent,
) -> None:
    """Inject one configured Galaris speech resource into Hermes."""
    from app.agent import parse_voice_selection

    selection = parse_voice_selection(getattr(agent, "voice", None))
    if selection is None or selection.mode != "tts":
        return
    llm = await llm_service.get_llm(selection.model_id)
    if llm is None or "speech" not in llm.service_capabilities:
        raise RuntimeError(f"Ressource TTS invalide pour l'agent {agent.code}")

    provider = llm.provider
    api_key = llm_provider_service.decrypt_api_key(provider.api_key)
    catalog_code = str(provider.catalog_code or "").strip()
    provider_type = str(provider.provider_type or "").strip()
    voice = _voice_identifier(llm)
    section: dict[str, Any] = {}
    hermes_provider = ""

    if provider_type == "elevenlabs":
        hermes_provider = "galaris-elevenlabs"
        key = _require_tts_key(provider.name, api_key)
        data_env["ELEVENLABS_API_KEY"] = key
        data_env["GALARIS_ELEVENLABS_TTS_BASE_URL"] = provider.base_url.rstrip("/")
        model = str(
            provider.configuration.get("tts_model")
            or "eleven_multilingual_v2"
        ).strip()
        section = _command_tts_config("elevenlabs", voice, model=model)
    elif provider_type == "google_cloud_tts":
        hermes_provider = "galaris-google-cloud-tts"
        key = _require_tts_key(provider.name, api_key)
        data_env["GOOGLE_CLOUD_TTS_API_KEY"] = key
        section = _command_tts_config("google-cloud-tts", voice)
    elif provider_type == "azure_speech":
        hermes_provider = "galaris-azure-speech"
        key = _require_tts_key(provider.name, api_key)
        region = str(provider.configuration.get("region") or "").strip()
        if not region:
            raise RuntimeError("La région Azure Speech est requise pour le TTS Hermès")
        data_env["AZURE_SPEECH_KEY"] = key
        data_env["AZURE_SPEECH_REGION"] = region
        section = _command_tts_config("azure-speech", voice)
    elif catalog_code == "gemini":
        hermes_provider = "gemini"
        data_env["GEMINI_API_KEY"] = _require_tts_key(provider.name, api_key)
        section["voice" if llm.resource_type == "voice" else "model"] = voice
    elif catalog_code == "xai":
        hermes_provider = "xai"
        data_env["XAI_API_KEY"] = _require_tts_key(provider.name, api_key)
        section["voice_id"] = voice
    elif catalog_code == "mistral":
        hermes_provider = "mistral"
        data_env["MISTRAL_API_KEY"] = _require_tts_key(provider.name, api_key)
        section["voice_id" if llm.resource_type == "voice" else "model"] = voice
    elif provider_type == "openai_compatible":
        hermes_provider = "openai"
        data_env["VOICE_TOOLS_OPENAI_KEY"] = _require_tts_key(provider.name, api_key)
        section["voice" if llm.resource_type == "voice" else "model"] = voice
        section["base_url"] = provider.base_url.rstrip("/")
    else:
        raise RuntimeError(
            f"Le fournisseur {provider.name} n'est pas compatible avec le TTS Hermès"
        )

    tts = as_dict(config.setdefault("tts", {}))
    tts["provider"] = hermes_provider
    tts[_GALARIS_MANAGED_PROVIDER_KEY] = hermes_provider
    if hermes_provider.startswith("galaris-"):
        providers = as_dict(tts.setdefault("providers", {}))
        providers[hermes_provider] = section
    else:
        tts[hermes_provider] = section
    logger.info(
        "Hermes sync: configured Galaris TTS for {}: {} via {}",
        agent.code,
        voice,
        provider.name,
    )


async def _inject_stt(
    config: dict[str, Any],
    data_env: dict[str, str],
    agent: Agent,
) -> None:
    """Inject the global Galaris transcription model as the Hermes STT provider.

    OpenAI-compatible providers are configured directly in Hermes: the selected
    model, provider base URL and decrypted provider token are passed to its native
    OpenAI transcription client. This notably covers OpenRouter, whose current STT
    endpoint accepts OpenAI multipart requests.
    """
    llm = await llm_service.get_transcription_llm(agent.id)
    if llm is None:
        return

    provider = llm.provider
    api_key = llm_provider_service.decrypt_api_key(provider.api_key)
    catalog_code = str(provider.catalog_code or "").strip()
    provider_type = str(provider.provider_type or "").strip()
    model = str(llm.llm_name or "").strip()
    section: dict[str, Any] = {}
    hermes_provider = ""
    key_env = ""

    if catalog_code == "groq":
        hermes_provider = "groq"
        key_env = "GROQ_API_KEY"
        # Hermes reads the Groq STT model from the environment, not from config.yaml.
        if model:
            data_env["STT_GROQ_MODEL"] = model
    elif catalog_code == "mistral":
        hermes_provider = "mistral"
        key_env = "MISTRAL_API_KEY"
        if model:
            section["model"] = model
    elif catalog_code == "xai":
        # xAI Grok STT exposes no model selection.
        hermes_provider = "xai"
        key_env = "XAI_API_KEY"
    elif provider_type == "elevenlabs":
        hermes_provider = "elevenlabs"
        key_env = "ELEVENLABS_API_KEY"
        if model:
            # Hermes calls the batch /speech-to-text endpoint, which rejects
            # the realtime Scribe variants (e.g. scribe_v2_realtime).
            model = model.removesuffix("_realtime")
            section["model_id"] = model
    elif provider_type == "openai_compatible":
        # Config-level values win inside Hermes, so this never collides with the
        # VOICE_TOOLS_OPENAI_KEY a TTS injection may also set. Hermes rewrites
        # Groq-only Whisper model names to whisper-1 on this path.
        if provider.catalog_code == "openrouter" and not api_key:
            logger.warning(
                "Hermes sync: provider {} has no API key; skipping STT injection for {}",
                provider.name,
                agent.code,
            )
            return
        hermes_provider = "openai"
        section["model"] = model or "whisper-1"
        section["base_url"] = llm_provider_service.transcription_base_url(provider)
        # Hermes requires a non-empty key even for keyless self-hosted Whisper servers.
        section["api_key"] = api_key or "galaris"
    else:
        logger.warning(
            "Hermes sync: transcription model {} ({}) has no Hermes STT equivalent; "
            "skipping STT injection for {}",
            llm.llm_name,
            provider.name,
            agent.code,
        )
        return

    if key_env:
        if not api_key:
            logger.warning(
                "Hermes sync: provider {} has no API key; skipping STT injection for {}",
                provider.name,
                agent.code,
            )
            return
        data_env[key_env] = api_key

    stt = as_dict(config.setdefault("stt", {}))
    stt["enabled"] = True
    stt["provider"] = hermes_provider
    stt[_GALARIS_MANAGED_PROVIDER_KEY] = hermes_provider
    if section:
        stt[hermes_provider] = section
    logger.info(
        "Hermes sync: configured Galaris STT for {}: {} via {}",
        agent.code,
        model or hermes_provider,
        provider.name,
    )


def _inject_mcp(config: dict[str, Any], agent: "Agent", api_url: str, mcp_token: str | None) -> None:
    """Inject the stateless Galaris Streamable HTTP MCP endpoint and system token."""
    if not mcp_token or not api_url:
        return

    mcp_url = f"{api_url.rstrip('/')}/mcp/{agent.code}"

    # Hermes treats explicit ``http`` as Streamable HTTP; only ``sse`` selects SSE.
    config.setdefault("mcp_servers", {})
    config["mcp_servers"]["galaris"] = {
        "transport": "http",
        "url": mcp_url,
        "headers": {
            "Authorization": f"Bearer {mcp_token}",
        },
    }


def _inject_memory_provider(
    config: dict[str, Any],
    data_env: dict[str, str],
    agent: "Agent",
    api_url: str,
    token: str | None,
) -> None:
    """Select the packaged Galaris MemoryProvider for managed Hermes profiles."""

    for key in (
        _GALARIS_MEMORY_URL_ENV,
        _GALARIS_MEMORY_TOKEN_ENV,
        _GALARIS_MEMORY_AGENT_ENV,
    ):
        data_env.pop(key, None)
    existing_memory = config.get("memory")
    if isinstance(existing_memory, dict):
        memory = as_dict(existing_memory)
        if memory.get("provider") == "galaris":
            memory.pop("provider", None)
    raw_plugins = config.get("plugins")
    if isinstance(raw_plugins, dict):
        plugins = as_dict(raw_plugins)
        for key in ("enabled", "disabled"):
            raw_values = plugins.get(key)
            if not isinstance(raw_values, list):
                continue
            values = [
                value
                for value in as_list(raw_values)
                if str(value).strip() != _GALARIS_MEMORY_PLUGIN_KEY
            ]
            if values:
                plugins[key] = values
            else:
                plugins.pop(key, None)
        if not plugins:
            config.pop("plugins", None)
    if not token or not api_url or not runtime_settings.MEMORY_CONTEXT_ENABLED:
        return
    memory = as_dict(config.setdefault("memory", {}))
    memory["provider"] = "galaris"
    plugins = as_dict(config.setdefault("plugins", {}))
    enabled = (
        list(as_list(plugins.get("enabled")))
        if isinstance(plugins.get("enabled"), list)
        else []
    )
    enabled.append(_GALARIS_MEMORY_PLUGIN_KEY)
    plugins["enabled"] = enabled
    data_env.update(
        {
            _GALARIS_MEMORY_URL_ENV: (
                f"{api_url.rstrip('/')}/memory/provider"
            ),
            _GALARIS_MEMORY_TOKEN_ENV: token,
            _GALARIS_MEMORY_AGENT_ENV: str(agent.id),
        }
    )


def _strip_galaris_builtin_memory_defaults(
    config: dict[str, Any],
) -> dict[str, Any]:
    """Remove values emitted by an earlier sync before rebuilding config layers."""

    cleaned = copy.deepcopy(config)
    memory = cleaned.get("memory")
    if isinstance(memory, dict):
        memory_config = as_dict(memory)
        for key in ("memory_enabled", "user_profile_enabled"):
            if memory_config.get(key) is False:
                memory_config.pop(key, None)
        if not memory_config:
            cleaned.pop("memory", None)

    agent = cleaned.get("agent")
    if isinstance(agent, dict):
        agent_config = as_dict(agent)
        disabled = [
            value
            for value in as_list(agent_config.get("disabled_toolsets"))
            if str(value) != "memory"
        ]
        if "disabled_toolsets" in agent_config:
            if disabled:
                agent_config["disabled_toolsets"] = disabled
            else:
                agent_config.pop("disabled_toolsets", None)
        if not agent_config:
            cleaned.pop("agent", None)

    skills = cleaned.get("skills")
    if isinstance(skills, dict):
        skills_config = as_dict(skills)
        managed_disabled = {
            str(value)
            for value in as_list(
                skills_config.pop(_LEGACY_GALARIS_MANAGED_DISABLED_SKILLS_KEY, [])
            )
        }
        if managed_disabled and "disabled" in skills_config:
            disabled = [
                value
                for value in as_list(skills_config.get("disabled"))
                if str(value) not in managed_disabled
            ]
            if disabled:
                skills_config["disabled"] = disabled
            else:
                skills_config.pop("disabled", None)
        if not skills_config:
            cleaned.pop("skills", None)
    return cleaned


def _has_disabled_toolsets_override(*configs: dict[str, Any]) -> bool:
    """Return whether a canonical override explicitly owns the toolset list."""

    return any(
        isinstance(config.get("agent"), dict)
        and "disabled_toolsets" in as_dict(config.get("agent"))
        for config in configs
    )


def _align_builtin_memory_toolset(
    config: dict[str, Any],
    *,
    disabled_toolsets_overridden: bool,
) -> None:
    """Expose Hermes' native tool exactly when its file-backed store is enabled."""

    memory = as_dict(config.get("memory"))
    builtin_enabled = bool(
        memory.get("memory_enabled") or memory.get("user_profile_enabled")
    )
    raw_agent = config.get("agent")
    agent = as_dict(raw_agent) if isinstance(raw_agent, dict) else {}
    config["agent"] = agent
    disabled = list(as_list(agent.get("disabled_toolsets")))
    without_memory = [value for value in disabled if str(value) != "memory"]

    if not builtin_enabled:
        agent["disabled_toolsets"] = [*without_memory, "memory"]
        return
    if disabled_toolsets_overridden:
        return
    if without_memory:
        agent["disabled_toolsets"] = without_memory
    else:
        agent.pop("disabled_toolsets", None)
    if not agent:
        config.pop("agent", None)


def _align_galaris_browser_toolset(
    config: dict[str, Any],
    *,
    enabled: bool,
    disabled_toolsets_overridden: bool,
) -> None:
    """Avoid exposing Hermes' browser alongside the governed Galaris browser."""

    raw_agent = config.get("agent")
    agent = as_dict(raw_agent) if isinstance(raw_agent, dict) else {}
    disabled = list(as_list(agent.get("disabled_toolsets")))
    without_browser = [value for value in disabled if str(value) != "browser"]
    if enabled:
        config["agent"] = agent
        agent["disabled_toolsets"] = [*without_browser, "browser"]
        return
    if disabled_toolsets_overridden:
        return
    if without_browser:
        config["agent"] = agent
        agent["disabled_toolsets"] = without_browser
    else:
        agent.pop("disabled_toolsets", None)
        if not agent:
            config.pop("agent", None)


def _align_galaris_image_toolsets(
    config: dict[str, Any],
    *,
    generation_enabled: bool,
    vision_enabled: bool,
    disabled_toolsets_overridden: bool,
) -> None:
    """Avoid duplicating the governed Galaris image functions in Hermes."""

    raw_agent = config.get("agent")
    agent = as_dict(raw_agent) if isinstance(raw_agent, dict) else {}
    disabled = list(as_list(agent.get("disabled_toolsets")))
    managed = {
        "image_gen": generation_enabled,
        "vision": vision_enabled,
    }
    aligned = [value for value in disabled if str(value) not in managed]
    if disabled_toolsets_overridden:
        aligned = list(disabled)
    for toolset, enabled in managed.items():
        if enabled and toolset not in {str(value) for value in aligned}:
            aligned.append(toolset)

    if aligned:
        config["agent"] = agent
        agent["disabled_toolsets"] = aligned
    else:
        agent.pop("disabled_toolsets", None)
        if not agent:
            config.pop("agent", None)


def _remove_galaris_terminal_injection(config: dict[str, Any]) -> None:
    """Restore terminal values which preceded Galaris' last SSH projection."""

    raw_marker = config.pop(_GALARIS_MANAGED_TERMINAL_KEY, None)
    if not isinstance(raw_marker, dict):
        return
    marker = as_dict(raw_marker)
    previous = as_dict(marker.get("previous"))
    absent = {str(value) for value in as_list(marker.get("absent"))}
    raw_terminal = config.get("terminal")
    terminal = as_dict(raw_terminal) if isinstance(raw_terminal, dict) else {}
    for key in _GALARIS_SSH_CONFIG_FIELDS:
        if key in previous:
            terminal[key] = previous[key]
        elif key in absent:
            terminal.pop(key, None)
    if terminal:
        config["terminal"] = terminal
    else:
        config.pop("terminal", None)


def _inject_galaris_ssh_terminal(
    config: dict[str, Any],
    data_env: dict[str, str],
    ssh: _HermesSshConnection,
    *,
    runtime_root: str,
) -> None:
    """Route Hermes' native terminal through one governed Console connection."""

    raw_terminal = config.get("terminal")
    terminal = as_dict(raw_terminal) if isinstance(raw_terminal, dict) else {}
    previous = {
        field: copy.deepcopy(terminal[field])
        for field in _GALARIS_SSH_CONFIG_FIELDS
        if field in terminal
    }
    config[_GALARIS_MANAGED_TERMINAL_KEY] = {
        "previous": previous,
        "absent": [
            field for field in _GALARIS_SSH_CONFIG_FIELDS if field not in terminal
        ],
    }
    for key in ("ssh_host", "ssh_user", "ssh_port", "ssh_key"):
        terminal.pop(key, None)
    terminal.update(
        {
            "backend": "ssh",
            "cwd": "~",
            "timeout": ssh.command_timeout_s,
        }
    )
    config["terminal"] = terminal

    ssh_root = f"{runtime_root}/.galaris/ssh"
    wrapper_path = f"{ssh_root}/bin"
    configured_path = data_env.get("PATH", "").strip() or _HERMES_RUNTIME_PATH
    data_env.update(
        {
            "PATH": f"{wrapper_path}:{configured_path}",
            "TERMINAL_ENV": "ssh",
            "TERMINAL_CWD": "~",
            "TERMINAL_TIMEOUT": str(ssh.command_timeout_s),
            "TERMINAL_SSH_HOST": ssh.host,
            "TERMINAL_SSH_USER": ssh.username,
            "TERMINAL_SSH_PORT": str(ssh.port),
            "TERMINAL_SSH_KEY": f"{ssh_root}/id_key",
            "TERMINAL_SSH_PERSISTENT": "true",
        }
    )


def _ssh_wrapper(binary: str, *, runtime_root: str, connect_timeout_s: float) -> str:
    """Build a profile-scoped OpenSSH wrapper enforcing Galaris host trust."""

    known_hosts = f"{runtime_root}/.galaris/ssh/known_hosts"
    timeout = max(1, math.ceil(connect_timeout_s))
    return (
        "#!/bin/sh\n"
        f'exec /usr/bin/{binary} '
        f'-o UserKnownHostsFile="{known_hosts}" '
        "-o StrictHostKeyChecking=yes "
        "-o IdentitiesOnly=yes "
        f"-o ConnectTimeout={timeout} \"$@\"\n"
    )


def _merge_hermes_config_layers(
    config_on_disk: dict[str, Any],
    default_config: dict[str, Any],
    agent_config: dict[str, Any],
    *,
    galaris_memory_enabled: bool,
    galaris_browser_enabled: bool | None = None,
    galaris_image_generation_enabled: bool | None = None,
    galaris_image_vision_enabled: bool | None = None,
) -> dict[str, Any]:
    """Merge generated defaults, Params, then per-agent config in priority order."""

    config = _strip_galaris_builtin_memory_defaults(config_on_disk)
    if galaris_memory_enabled:
        config = deep_merge(config, _GALARIS_BUILTIN_MEMORY_DEFAULTS)
    config = deep_merge(config, default_config)
    config = deep_merge(config, agent_config)
    if galaris_memory_enabled:
        _align_builtin_memory_toolset(
            config,
            disabled_toolsets_overridden=_has_disabled_toolsets_override(
                default_config,
                agent_config,
            ),
        )
    if galaris_browser_enabled is not None:
        _align_galaris_browser_toolset(
            config,
            enabled=galaris_browser_enabled,
            disabled_toolsets_overridden=_has_disabled_toolsets_override(
                default_config,
                agent_config,
            ),
        )
    if (
        galaris_image_generation_enabled is not None
        and galaris_image_vision_enabled is not None
    ):
        _align_galaris_image_toolsets(
            config,
            generation_enabled=galaris_image_generation_enabled,
            vision_enabled=galaris_image_vision_enabled,
            disabled_toolsets_overridden=_has_disabled_toolsets_override(
                default_config,
                agent_config,
            ),
        )
    return config


def _template_destinations(filepath: str) -> tuple[str, ...]:
    """Project the memory provider in modern and Hermes 0.18 layouts."""

    if not filepath.startswith(_GALARIS_MEMORY_TEMPLATE_PREFIX):
        return (filepath,)
    suffix = filepath.removeprefix(_GALARIS_MEMORY_TEMPLATE_PREFIX)
    return (filepath, f"{_GALARIS_MEMORY_LEGACY_PREFIX}{suffix}")


def _inject_dashboard_auth(config: dict[str, Any], agent: "Agent") -> None:
    """Inject Hermes dashboard basic authentication when configured."""
    if not agent.hermes_dashboard_enabled:
        return
    username = (agent.hermes_dashboard_username or "admin").strip()
    password_hash = _decrypt(agent.hermes_dashboard_password_hash) if agent.hermes_dashboard_password_hash else ""
    if not username or not password_hash:
        return

    dashboard = as_dict(config.setdefault("dashboard", {}))
    basic_auth = as_dict(dashboard.setdefault("basic_auth", {}))
    basic_auth["username"] = username
    basic_auth["password_hash"] = password_hash


def _build_compose_dict(
    agent: "Agent",
    uid: int,
    gid: int,
    default_compose: str | None = None,
) -> dict[str, Any]:
    """Apply global then agent overrides; network topology belongs to the operator."""
    compose = copy.deepcopy(_DEFAULT_COMPOSE)
    compose["services"]["agent"]["container_name"] = f"{agent.code}-agent"
    compose["services"]["agent"]["environment"].extend([
        f"HERMES_UID={uid}",
        f"HERMES_GID={gid}",
    ])

    ports: list[str] = []
    if agent.hermes_api_port is not None:
        ports.append(f"{agent.hermes_api_port}:8642")
    if agent.hermes_dashboard_enabled and agent.hermes_dashboard_port is not None:
        ports.append(f"{agent.hermes_dashboard_port}:9119")
    if ports:
        compose["services"]["agent"]["ports"] = ports

    compose = merge_compose_defaults(compose, default_compose, service_name="agent")
    if agent.hermes_compose:
        agent_dict = cast(dict[str, Any], yaml.safe_load(agent.hermes_compose) or {})  # type: ignore[reportUnknownMemberType]
        compose = deep_merge(compose, agent_dict)

    return compose


def _runtime_url(agent_code: str) -> str:
    """Return the stable URL reachable from the shared harness network."""
    return f"http://{agent_code}-agent:8642/v1"


def _sanitize_soul_text(value: str) -> str:
    """Remove invisible characters that trigger Hermes prompt-injection guards."""
    return "".join(
        char
        for char in value
        if unicodedata.category(char) != "Cf"
        and (unicodedata.category(char) != "Cc" or char in {"\n", "\r", "\t"})
    )


def _build_soul_content(agent: "Agent") -> str:
    """Build the SOUL.md file that defines Hermes agent identity."""
    title_label = _sanitize_soul_text(agent.title.label if agent.title else "")
    first_name = _sanitize_soul_text(agent.first_name or "")
    last_name = _sanitize_soul_text(agent.last_name or "")
    full_name = f"{title_label} {first_name} {last_name}".strip()
    job_title = _sanitize_soul_text(agent.job_title or "Not defined")
    personality = agent.personality or "Not defined"
    job_description = agent.job_description or "Not defined"

    return f"""# Identity

**Title:** {title_label}
**First name:** {first_name}
**Last name:** {last_name}
**Full name:** {full_name}
**Job title:** {job_title}

# Personality

{personality}

# Job description

{job_description}
"""


def _render(content: str, variables: dict[str, str]) -> str:
    """Substitute known ${key} values while preserving other template variables."""
    return re.sub(
        r'\$\{([^}]+)\}',
        lambda m: variables.get(m.group(1), m.group(0)),
        content,
    )


class HermesAgent:
    """Async controller for one virtual agent's Hermes runtime."""

    def __init__(self, agent: Agent, manager: "HermesManager") -> None:
        self.agent = agent
        self._manager = manager

    @property
    def code(self) -> str:
        if not self.agent.code:
            raise RuntimeError(_message("agent_code_missing", agent_id=self.agent.id))
        return self.agent.code

    # Lifecycle

    async def create(self, template: str | None = None) -> None:
        """Create the agent directory on the bridge server."""
        await self._manager.create_agent(self.code, template)

    async def delete(self) -> None:
        """Stop and remove the agent from the bridge server."""
        await self._manager.delete_agent(self.code)

    async def get_status(self) -> str:
        """Return container status: running, stopped, absent, or unknown."""
        return await self._manager.get_agent_status(self.code)

    async def start(self) -> str:
        """Synchronize configuration, then start the agent's Docker container."""
        async with self._manager.agent_lock(self.code):
            await self._sync_config()
            return await self._manager.run_agent_command(self.code, "start")

    async def stop(self) -> str:
        """Stop the agent's Docker container."""
        return await self._manager.run_agent_command(self.code, "stop")

    async def get_logs(self, lines: int = 300) -> list[str]:
        """Return recent Docker Compose logs."""
        return await self._manager.get_agent_logs(self.code, lines)

    async def restart(self) -> str:
        """Inject configuration and restart the agent container."""
        async with self._manager.agent_lock(self.code):
            await self._sync_config()
            return await self._manager.run_agent_command(self.code, "restart")

    async def update(self) -> str:
        """Inject configuration and update the Hermes runtime."""
        async with self._manager.agent_lock(self.code):
            await self._sync_config()
            return await self._manager.run_agent_command(self.code, "update")

    # Files

    async def read_file(self, filepath: str) -> str:
        """Read a file from the agent directory."""
        return await self._manager.read_agent_file(self.code, filepath)

    async def write_file(
        self,
        filepath: str,
        content: str,
        *,
        mode: int = 0o644,
    ) -> None:
        """Write or create a file in the agent directory."""
        if mode == 0o644:
            await self._manager.write_agent_file(self.code, filepath, content)
        else:
            await self._manager.write_agent_file(
                self.code,
                filepath,
                content,
                mode=mode,
            )

    async def _sync_console_ssh(
        self,
        data_env: dict[str, str],
        config: dict[str, Any],
        ssh: _HermesSshConnection | None,
    ) -> None:
        """Materialize and select an external Console connection for Hermes."""

        if ssh is None:
            await self._manager.delete_agent_tree(self.code, _GALARIS_SSH_DIR)
            return

        runtime_root = "/opt/data"
        files = (
            (
                f"{_GALARIS_SSH_DIR}/known_hosts",
                _render_known_hosts(ssh),
                0o600,
            ),
            (
                f"{_GALARIS_SSH_DIR}/bin/ssh",
                _ssh_wrapper(
                    "ssh",
                    runtime_root=runtime_root,
                    connect_timeout_s=ssh.connect_timeout_s,
                ),
                0o755,
            ),
            (
                f"{_GALARIS_SSH_DIR}/bin/scp",
                _ssh_wrapper(
                    "scp",
                    runtime_root=runtime_root,
                    connect_timeout_s=ssh.connect_timeout_s,
                ),
                0o755,
            ),
            # Switch the identity only after the strict trust policy and both
            # clients are ready. A concurrent old runtime may fail closed
            # during rotation, but cannot observe a new key with old trust.
            (
                f"{_GALARIS_SSH_DIR}/id_key",
                _export_openssh_private_key(ssh),
                0o600,
            ),
        )
        for filepath, content, mode in files:
            await self.write_file(filepath, content, mode=mode)
        _inject_galaris_ssh_terminal(
            config,
            data_env,
            ssh,
            runtime_root=runtime_root,
        )

    async def _inject(
        self,
        data_env: dict[str, str],
        config: dict[str, Any],
        mcp_token: str | None = None,
    ) -> None:
        """Inject dynamic data into Hermes configuration files."""
        _inject_dashboard_auth(config, self.agent)
        if not mcp_token:
            raise RuntimeError(_message("system_token_missing", agent_code=self.code))
        llm = await _get_effective_llm(self.agent)
        if llm is None:
            raise RuntimeError(_message("model_missing", agent_code=self.code))
        _remove_direct_llm_credentials(data_env)
        _inject_llm(config, data_env, llm, mcp_token)
        vision_llm = (
            llm
            if llm.input_image
            else await llm_service.get_vision_llm(
                exclude_llm_id=llm.id,
                agent_id=self.agent.id,
            )
        )
        if vision_llm is not None:
            _inject_vision_llm(config, data_env, vision_llm, mcp_token)
            logger.info(
                "Hermes sync: configured Galaris vision model for {}: {}",
                self.code,
                vision_llm.llm_name,
            )
        else:
            auxiliary = config.get("auxiliary")
            if isinstance(auxiliary, dict):
                as_dict(auxiliary).pop("vision", None)
        await _inject_tts(config, data_env, self.agent)
        await _inject_stt(config, data_env, self.agent)
        _inject_mcp(
            config,
            self.agent,
            runtime_settings.HARNESS_API_URL,
            mcp_token,
        )
        _inject_memory_provider(
            config,
            data_env,
            self.agent,
            runtime_settings.HARNESS_API_URL,
            mcp_token,
        )

    async def _load_config(self) -> dict[str, Any] | None:
        """Load data/config.yaml, returning null when the remote file is absent."""
        try:
            content = await self.read_file("data/config.yaml")
            return cast(dict[str, Any], yaml.safe_load(content) or {})  # type: ignore[reportUnknownMemberType]
        except Exception:
            return None

    async def _restore_bundled_skills_opt_in(self) -> None:
        """Undo the short-lived Galaris opt-out without deleting user markers."""

        try:
            marker = await self.read_file(_HERMES_NO_BUNDLED_SKILLS_MARKER)
        except Exception:
            return
        if marker != _GALARIS_BUNDLED_SKILLS_MARKER_CONTENT:
            return
        await self._manager.delete_agent_file(
            self.code,
            _HERMES_NO_BUNDLED_SKILLS_MARKER,
        )

    async def _sync_config(self) -> None:
        """Idempotently inject complete agent configuration without restarting."""
        # Ensure the runtime and template exist.
        existing = await self._manager.list_agents()
        if self.code not in existing:
            await self.create()
        await self._restore_bundled_skills_opt_in()
        await self.push_config()

        # Rotate tokens on every sync to limit exposure and prevent direct access.
        new_api_key = secrets.token_urlsafe(32)
        try:
            await config_service.update_runtime_target(
                self.agent,
                api_key=new_api_key,
                url=_runtime_url(self.code),
                model="hermes-agent",
            )
            await config_service.hydrate_agent(self.agent)
        except Exception as e:
            logger.warning("Hermes sync: API key rotation failed for agent={}: {}", self.code, e)

        # Rotate the hidden system MCP token used by the per-agent HTTP endpoint.
        mcp_token: str | None = None
        try:
            from app.mcp import mcp_token_service
            mcp_token = await mcp_token_service.rotate_system_token(self.agent.id)
        except Exception as e:
            logger.warning("Hermes sync: MCP system token rotation failed for agent={}: {}", self.code, e)

        default_compose = await params_service.get(Params.HARNESS_DEFAULT_COMPOSE)
        default_config  = await params_service.get(Params.HERMES_DEFAULT_CONFIG)
        sys_info = await self._manager.get_system_info()
        env = _default_env_dict(self.agent)
        compose = _build_compose_dict(
            self.agent,
            sys_info["uid"],
            sys_info["gid"],
            default_compose,
        )
        _remove_direct_llm_compose_credentials(compose)
        for filepath, file_content in [
            (".env", _serialize_env(env)),
            (
                "compose.yaml",
                cast(
                    str,
                    yaml.dump(compose, allow_unicode=True, sort_keys=False),
                ),  # type: ignore[reportUnknownMemberType]
            ),
        ]:
            try:
                await self.write_file(filepath, file_content)
            except Exception as e:
                logger.warning(
                    "Hermes sync ignored failed write: agent={} file={} error={}",
                    self.code,
                    filepath,
                    e,
                )

        # A missing config lets Hermes create its own defaults on first start.
        config_on_disk: dict[str, Any] | None = await self._load_config()
        if config_on_disk is not None:
            _remove_galaris_tts_injection(config_on_disk)
            _remove_galaris_stt_injection(config_on_disk)
            _remove_galaris_terminal_injection(config_on_disk)
        # Merge Galaris defaults, configured Params, and per-agent overrides.
        data_env: dict[str, str] = dict(_DEFAULT_DATA_ENV)
        default_config_dict: dict[str, Any] = {}
        if default_config:
            default_config_dict = cast(dict[str, Any], yaml.safe_load(default_config) or {})  # type: ignore[reportUnknownMemberType]
        agent_config_dict: dict[str, Any] = {}
        if self.agent.hermes_config:
            agent_config_dict = cast(dict[str, Any], yaml.safe_load(self.agent.hermes_config) or {})  # type: ignore[reportUnknownMemberType]
        from app.connection import connection_service
        from app.tools import list_enabled_native_mcp_definitions
        from core.database import get_db_session

        async with get_db_session():
            galaris_browser_enabled = await connection_service.has_active_tool_connection(
                self.agent.id,
                "browser",
            )
            native_definitions = await list_enabled_native_mcp_definitions(
                self.agent.id,
                runtime="hermes",
            )
            console_ssh = await _resolve_external_console_ssh(self.agent.id)
        native_function_names = {definition.name for definition in native_definitions}
        config = _merge_hermes_config_layers(
            config_on_disk or {},
            default_config_dict,
            agent_config_dict,
            galaris_memory_enabled=runtime_settings.MEMORY_CONTEXT_ENABLED,
            galaris_browser_enabled=galaris_browser_enabled,
            galaris_image_generation_enabled=(
                "image_generate" in native_function_names
            ),
            galaris_image_vision_enabled="image_read" in native_function_names,
        )

        # Priority increases from generated values to global and then agent overrides.
        data_env.update(await _load_global_data_env())
        if self.agent.hermes_data_env:
            data_env.update(decrypt_mapping_values(self.agent.hermes_data_env))

        # Enforce Galaris proxy routing after every operator-provided layer.
        await self._inject(data_env, config, mcp_token)
        await self._sync_console_ssh(data_env, config, console_ssh)

        # Send final data files.
        config_yaml = cast(
            str,
            yaml.dump(config, allow_unicode=True, sort_keys=False),
        )  # type: ignore[reportUnknownMemberType]
        data_files: list[tuple[str, str]] = [
            ("data/.env", _serialize_env(data_env)),
            ("data/SOUL.md", _build_soul_content(self.agent)),
            ("data/config.yaml", config_yaml),
        ]
        for filepath, file_content in data_files:
            try:
                await self.write_file(filepath, file_content)
            except Exception as e:
                logger.warning(
                    "Hermes sync ignored failed write: agent={} file={} error={}",
                    self.code,
                    filepath,
                    e,
                )

        # Project only centrally assigned skills under a dedicated managed subtree.
        from .skill_sync import sync_managed_skills
        await sync_managed_skills(self.agent, self._manager)

        logger.info("Hermes configuration synchronized for agent={}", self.code)

    async def sync(self) -> None:
        """Create if necessary, inject configuration, and restart the runtime."""
        async with self._manager.agent_lock(self.code):
            await self._sync_config()
            await self._manager.run_agent_command(self.code, "restart")
        logger.info("Hermes sync completed for agent={}", self.code)

    async def push_config(self, extra_variables: dict[str, str] | None = None) -> list[str]:
        """Idempotently render and push every default-agent template file."""
        if not _DEFAULT_AGENT_DIR.is_dir():
            raise RuntimeError(_message("template_missing", path=_DEFAULT_AGENT_DIR))

        variables: dict[str, str] = {
            "agent.code":       self.code,
            "agent.first_name": self.agent.first_name,
            "agent.last_name":  self.agent.last_name,
        }
        if extra_variables:
            variables.update(extra_variables)

        pushed: list[str] = []
        errors: list[str] = []
        for src in sorted(_DEFAULT_AGENT_DIR.rglob("*")):
            if src.is_dir():
                continue
            filepath = src.relative_to(_DEFAULT_AGENT_DIR).as_posix()
            try:
                content = src.read_text(encoding="utf-8")
                rendered = _render(content, variables)
            except Exception as e:
                logger.warning(
                    "Hermes config template failed: agent={} file={} error={}",
                    self.code,
                    filepath,
                    e,
                )
                errors.append(filepath)
                continue
            for destination in _template_destinations(filepath):
                try:
                    await self.write_file(destination, rendered)
                    pushed.append(destination)
                except Exception as e:
                    logger.warning(
                        "Hermes config file failed: agent={} file={} error={}",
                        self.code,
                        destination,
                        e,
                    )
                    errors.append(destination)

        if errors:
            logger.warning("Hermes config pushed with errors: agent={} ok={} errors={}", self.code, pushed, errors)
        else:
            logger.info("Hermes config pushed: agent={} files={}", self.code, len(pushed))
        return pushed


class HermesManager:
    """Compose Hermes-specific policy with generic harness management."""

    def agent_lock(self, agent_code: str) -> asyncio.Lock:
        """Serialize configuration syncs and restarts for one agent.

        Two overlapping ``docker compose down``/``up`` runs race on the fixed
        container name and can leave the agent stopped.
        """
        return harness_manager.instance_lock(agent_code)

    # Agent operations called by HermesAgent.

    async def get_agent_status(self, agent_id: str) -> str:
        """Return Docker status: running, stopped, absent, or unknown."""
        return await harness_manager.get_instance_status(agent_id)

    async def create_agent(self, name: str, template: str | None = None) -> None:
        await harness_manager.create_instance(name, template)
        logger.info("Hermes agent created: code={}", name)

    async def delete_agent(self, agent_id: str) -> None:
        await harness_manager.delete_instance(agent_id)
        logger.info("Hermes agent deleted: code={}", agent_id)

    async def run_agent_command(self, agent_id: str, command: str) -> str:
        return await harness_manager.run_action(agent_id, command)

    async def read_agent_file(self, agent_id: str, filepath: str) -> str:
        return await harness_manager.read_text_file(agent_id, filepath)

    async def write_agent_file(
        self,
        agent_id: str,
        filepath: str,
        content: str,
        *,
        mode: int = 0o644,
    ) -> None:
        if mode == 0o644:
            await harness_manager.write_text_file(agent_id, filepath, content)
        else:
            await harness_manager.write_text_file(
                agent_id,
                filepath,
                content,
                mode=mode,
            )

    async def download_agent_file_to(self, agent_id: str, filepath: str, dest: Path) -> int:
        """Stream a raw agent file to ``dest`` with constant memory usage."""
        return await harness_manager.download_file_to(agent_id, filepath, dest)

    async def delete_agent_file(self, agent_id: str, filepath: str) -> None:
        """Delete an agent file after delivery or explicit cleanup."""
        await harness_manager.delete_file(agent_id, filepath)

    async def delete_agent_tree(self, agent_id: str, dirpath: str) -> bool:
        """Recursively purge an agent directory and report whether it existed."""
        return await harness_manager.delete_tree(agent_id, dirpath)

    async def upload_agent_file_from(self, agent_id: str, filepath: str, src: Path) -> int:
        """Stream local ``src`` into an agent runtime directory with constant memory usage."""
        return await harness_manager.upload_file_from(agent_id, filepath, src)

    @staticmethod
    def _kanban_transport(value: str) -> str:
        transport = value.strip().lower()
        if transport != "legacy":
            raise RuntimeError(_message("kanban_transport_invalid", transport=value))
        return transport

    @staticmethod
    def _kanban_task_id(value: str) -> str:
        task_id = value.strip().lower()
        if not _KANBAN_TASK_RE.fullmatch(task_id):
            raise RuntimeError(_message("kanban_task_id_invalid"))
        return task_id

    async def create_kanban_task(
        self,
        agent_id: str,
        *,
        transport: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a card through the transport frozen for this agent run."""

        self._kanban_transport(transport)
        del agent_id, payload
        raise RuntimeError(await tr("hermes.errors.kanban_management_unsupported"))

    async def get_kanban_task(
        self,
        agent_id: str,
        task_id: str,
        *,
        transport: str,
    ) -> dict[str, Any]:
        """Read one subordinate card through its original transport."""

        self._kanban_transport(transport)
        self._kanban_task_id(task_id)
        del agent_id
        raise RuntimeError(await tr("hermes.errors.kanban_management_unsupported"))

    async def dispatch_kanban(self, agent_id: str, *, transport: str) -> None:
        """Nudge a single worker after a card has become ready."""

        self._kanban_transport(transport)
        del agent_id
        raise RuntimeError(await tr("hermes.errors.kanban_management_unsupported"))

    async def cancel_kanban_task(
        self,
        agent_id: str,
        task_id: str,
        *,
        transport: str,
        reason: str,
    ) -> None:
        """Stop a worker and archive its card so it cannot be re-dispatched."""

        self._kanban_transport(transport)
        self._kanban_task_id(task_id)
        del agent_id, reason
        raise RuntimeError(await tr("hermes.errors.kanban_management_unsupported"))

    # Public API

    def get_agent(self, agent: Agent) -> HermesAgent:
        """Return a controller for this agent's Hermes instance."""
        return HermesAgent(agent=agent, manager=self)

    async def list_agents(self) -> list[str]:
        """List all agents declared on the bridge server."""
        return await harness_manager.list_instances()

    async def get_system_info(self) -> dict[str, int]:
        """Return bridge process UID and GID."""
        return await harness_manager.get_system_info()

    async def check_reachable(self) -> bool:
        """Return whether the configured Hermes management backend responds."""
        return await harness_manager.check_reachable()

    async def get_agent_logs(self, agent_id: str, lines: int = 300) -> list[str]:
        """Return recent Docker Compose log lines for an agent."""
        return await harness_manager.get_logs(agent_id, lines)

    async def check_model_available(self, agent: Agent) -> str:
        """Check whether ``hermes_model`` is exposed by the agent's /models endpoint."""
        if not agent.hermes_url or not agent.hermes_model:
            return "unknown"
        url = agent.hermes_url.rstrip("/") + "/models"
        headers: dict[str, str] = {}
        if agent.hermes_api_key:
            headers["Authorization"] = f"Bearer {_decrypt(agent.hermes_api_key)}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                if not resp.is_success:
                    return "stopped"
                data: dict[str, object] = resp.json()
                models: list[dict[str, object]] = (
                    data.get("data") or data.get("models") or []  # type: ignore[assignment]
                )
                found = any(
                    (m.get("id") or m.get("name")) == agent.hermes_model
                    for m in models
                )
                return "running" if found else "stopped"
        except httpx.RequestError:
            return "absent"
        except Exception:
            return "unknown"


manager = HermesManager()
