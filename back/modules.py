LLM_PROVIDER_MODULES = [
    "bridge.openrouter",
    "bridge.mammouth",
    "bridge.openai",
    "bridge.anthropic",
    "bridge.deepseek",
    "bridge.fireworks",
    "bridge.groq",
    "bridge.mistral",
    "bridge.models_dev",
    "bridge.together",
    "bridge.cerebras",
    "bridge.google",
    "bridge.xai",
    "bridge.nvidia",
    "bridge.huggingface",
    "bridge.cohere",
    "bridge.perplexity",
    "bridge.elevenlabs",
    "bridge.sunoapi",
    "bridge.byteplus",
    "bridge.azure_speech",
    "bridge.ollama",
]

AGENT_DRIVER_MODULES = [
    "app.harnesses.agent_driver",
    "bridge.hermes.agent_driver",
]

HARNESS_PROVIDER_MODULES = [
    "bridge.claude_agent.harness_provider",
    "bridge.codex.harness_provider",
    "bridge.deepseek_harness.harness_provider",
    "bridge.hermes.harness_provider",
]

HARNESS_SUPERVISOR_MODULES = [
    "bridge.hermes.harness_supervisor",
]


MODULES = [
    "core.user",
    "core.team",
    "core.authorize",
    "core.params",
    "core.dbadmin",
    "app.incident",
    "app.tools",
    "app.documentation",
    "app.agent",
    "app.harness",
    "app.harnesses",
    "app.connection",
    "app.skill",
    # Historical translation code retained; its retired router exposes no routes.
    "app.webhook",
    "app.llm",
    "app.topic",
    "app.memory",
    "app.contact",
    "app.dream",
    "app.task",
    "app.goal",
    "app.dashboard",
    "app.lab",
    "app.messenger",
    "app.chat",
    "app.conversation",
    "app.browser",
    "app.image",
    "app.audio",
    "app.onboarding",
    "app.voice",
    "app.file_share",
    "app.console",
    "app.process",
    "app.multimedia",
    "app.mcp",
    "bridge.harness",
    "bridge.claude_agent",
    "bridge.codex",
    "bridge.deepseek_harness",
    "bridge.n8n",
    "bridge.mail",
    "bridge.calendar",
    "bridge.hermes",
    "bridge.one_bot",
    "bridge.matrix",
    "bridge.nextcloud",
    "bridge.telegram",
    "bridge.whatsapp",
    *LLM_PROVIDER_MODULES,
]


def load_llm_provider_modules() -> None:
    """Import provider bridge roots at the composition boundary."""

    import importlib

    for module_name in LLM_PROVIDER_MODULES:
        importlib.import_module(module_name)


def configure_dream_media() -> None:
    """Bind specialist services without adding media-domain dependencies to Dream."""
    from app.audio import normalize_for_transcription_chunks_isolated
    from app.dream.interface import register_attachment_media
    from app.image import describe_image

    register_attachment_media(image_reader=describe_image, audio_normalizer=normalize_for_transcription_chunks_isolated)


def load_dbadmin_contributions(registry: object) -> None:
    """Load optional DbAdmin contributions at the composition boundary."""

    import importlib

    load_llm_provider_modules()
    for module_name in MODULES:
        try:
            contribution = importlib.import_module(f"{module_name}.dbadmin")
        except ModuleNotFoundError as exc:
            if exc.name in {module_name, f"{module_name}.dbadmin"}:
                continue
            raise
        register = getattr(contribution, "register_dbadmin", None)
        if register is not None:
            register(registry)

    composition = importlib.import_module("dbadmin_composition")
    composition.register_dbadmin(registry)
