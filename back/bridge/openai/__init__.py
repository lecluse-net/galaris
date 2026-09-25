"""OpenAI API and ChatGPT/Codex provider bridge registration."""

from dataclasses import replace

from pydantic_ai.profiles.openai import openai_model_profile
from pydantic_ai.profiles.openai_codex import openai_codex_model_profile

from app.llm.provider_catalog import ProviderProfile
from app.llm.provider_facade import (
    ProviderResponsesPolicy,
    ProviderRuntimePolicy,
    register_chat_transport,
    register_responses_transport,
    register_responses_policy,
    register_managed_runtime_authentication,
    register_provider,
    register_image_generation_provider,
    register_image_size_resolver,
    register_provider_authentication,
    register_provider_quota_reader,
    register_realtime_conversation_provider,
    register_resource_discovery,
    register_runtime_policy,
)

from .codex import CodexBridge
from .parameters import model_parameter_policy, chatgpt_parameter_policy
from app.llm.provider_facade import register_request_parameter_policy
from .resources import OpenAIResourceDiscovery
from .realtime import OpenAIRealtime
from .image import OpenAIImageGeneration, native_image_size


API_PROFILE = ProviderProfile(
    code="openai-api",
    display_name="OpenAI API",
    provider_type="openai_compatible",
    auth_type="api_key",
    base_url="https://api.openai.com/v1",
    token_url="https://platform.openai.com/api-keys",
    documentation_url="https://developers.openai.com/api/docs/quickstart",
    icon="auto_awesome",
    color="teal",
    models_dev_id="openai",
    supports_transcription=True,
    supports_responses=True,
    capabilities=(
        "chat",
        "vision",
        "image_generation",
        "embedding",
        "transcription",
        "speech",
        "realtime_conversation",
    ),
)
CODEX_PROFILE = ProviderProfile(
    code="openai-codex",
    display_name="OpenAI — ChatGPT",
    provider_type="openai_codex",
    auth_type="oauth_device",
    base_url="https://chatgpt.com/backend-api/codex",
    token_url=None,
    documentation_url="https://learn.chatgpt.com/docs/auth",
    icon="code",
    color="deep-purple",
    models_dev_id="openai",
    supports_responses=True,
)

register_provider(API_PROFILE)
register_image_size_resolver("openai", native_image_size)
register_image_generation_provider(API_PROFILE.code, OpenAIImageGeneration())
register_image_generation_provider("openai_compatible", OpenAIImageGeneration())
register_provider(CODEX_PROFILE)
register_request_parameter_policy(API_PROFILE.code, model_parameter_policy)
register_request_parameter_policy(CODEX_PROFILE.code, chatgpt_parameter_policy)
register_resource_discovery(API_PROFILE.code, OpenAIResourceDiscovery())
register_realtime_conversation_provider(API_PROFILE.code, OpenAIRealtime())
CODEX_BRIDGE = CodexBridge()
register_resource_discovery(CODEX_PROFILE.code, CODEX_BRIDGE)
register_provider_authentication(CODEX_PROFILE.code, CODEX_BRIDGE)
register_provider_quota_reader(CODEX_PROFILE.code, CODEX_BRIDGE)
register_managed_runtime_authentication(CODEX_PROFILE.code, CODEX_BRIDGE)
register_chat_transport(CODEX_PROFILE.code, CODEX_BRIDGE)
register_responses_transport(CODEX_PROFILE.code, CODEX_BRIDGE)
RESPONSES_POLICY = ProviderResponsesPolicy(
    model_profile=openai_model_profile,
    supports_compaction=True,
    store=False,
    reasoning_context="all_turns",
    reasoning_summary="auto",
    send_reasoning_ids=True,
)
register_responses_policy(API_PROFILE.code, RESPONSES_POLICY)
register_responses_policy(
    CODEX_PROFILE.code,
    replace(RESPONSES_POLICY, model_profile=openai_codex_model_profile),
)
register_runtime_policy(
    CODEX_PROFILE.code,
    ProviderRuntimePolicy(realtime_reasoning_effort="low"),
)

__all__ = ["API_PROFILE", "CODEX_PROFILE"]
