"""Optional installation defaults, created atomically before permanent datasets.

Only public model identifiers and capabilities are shipped. Credentials, account
configuration and pricing are deliberately absent; prices can be refreshed later.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import SchemaTransitionSet

from .profile_models import LlmProfile
from .profile_codes import profile_code
from .profile_service import DEFAULT_PROFILE_LABEL
from .provider_catalog import get_provider_profile
from .provider_models import LLM, LLMProvider


@dataclass(frozen=True)
class InitialModel:
    code: str
    name: str
    label: str
    capabilities: tuple[str, ...]
    context_length: int | None = None
    inputs: tuple[str, ...] = ("text",)
    outputs: tuple[str, ...] = ("text",)


INITIAL_MODELS = (
    InitialModel("deepseek-deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash",
                 "DeepSeek: DeepSeek V4.1 Flash", ("vision", "chat"), 1048576, ("text", "image")),
    InitialModel("openai-gpt-5.4-nano", "openai/gpt-5.4-nano", "GPT 5.4 Nano",
                 ("vision", "chat"), 400000, ("text", "image", "file")),
    InitialModel("whisper", "openai/whisper-large-v3", "Whisper", ("transcription",),
                 inputs=("text", "audio"), outputs=("text", "audio")),
    InitialModel("minimax-hailuo-3-max", "minimax/hailuo-3-max", "MiniMax: Hailuo 3 Max",
                 ("chat", "video_generation"), outputs=("video",)),
    InitialModel("google-lyria-3-clip-preview", "google/lyria-3-clip-preview",
                 "Google: Lyria 3 Clip Preview", ("music_generation",), 1048576,
                 ("text", "image"), ("text", "audio")),
    InitialModel("typesafe-jev-1.13", "typesafe/jev-1.13", "TypeSafe: Jev 1.13",
                 ("decision",), 32000, outputs=()),
    InitialModel("qwen-qwen3-embedding-4b", "qwen/qwen3-embedding-4b", "Qwen: Qwen3 Embedding 4B",
                 ("embedding",), 32768, outputs=()),
    InitialModel("google-gemini-3-pro-image", "google/gemini-3-pro-image",
                 "Google: Nano Banana Pro (Gemini 3 Pro Image)",
                 ("image_generation", "vision", "chat"), 131072, ("text", "image"), ("text", "image")),
    InitialModel("nvidia-nemotron-3-nano-omni-30b-a3b-reasoning-free",
                 "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                 "NVIDIA: Nemotron 3 Nano Omni (free)",
                 ("vision", "chat", "audio_understanding", "video_understanding"),
                 256000, ("text", "image", "video", "audio")),
)

INITIAL_SELECTIONS = {
    "text_ultra_low_llm_id": "deepseek-deepseek-v4.1-flash",
    "text_low_llm_id": "deepseek-deepseek-v4.1-flash",
    "text_standard_llm_id": "deepseek-deepseek-v4.1-flash",
    "text_high_llm_id": "deepseek-deepseek-v4.1-flash",
    "vision_llm_id": "deepseek-deepseek-v4.1-flash",
    "document_llm_id": "openai-gpt-5.4-nano",
    "transcription_llm_id": "whisper",
    "video_generation_llm_id": "minimax-hailuo-3-max",
    "music_generation_llm_id": "google-lyria-3-clip-preview",
    "decision_llm_id": "typesafe-jev-1.13",
    "vector_llm_id": "qwen-qwen3-embedding-4b",
    "image_llm_id": "google-gemini-3-pro-image",
    "audio_llm_id": "nvidia-nemotron-3-nano-omni-30b-a3b-reasoning-free",
    "video_llm_id": "nvidia-nemotron-3-nano-omni-30b-a3b-reasoning-free",
}


def needs_initial_configuration(transitions: SchemaTransitionSet) -> bool:
    """Never inject a commercial provider into an existing installation."""
    return {"llm_providers", "llms", "llm_profiles"}.issubset(transitions.added_tables)


async def initial_configuration_complete(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> bool:
    # This connection and its models/profile are committed atomically. Include
    # tombstones so a crash after commit cannot undo a subsequent user deletion.
    return await session.scalar(
        select(LLMProvider.id).where(LLMProvider.catalog_code == "openrouter")
        .execution_options(include_historized=True).limit(1)
    ) is not None


async def initialize_configuration(
    session: AsyncSession, transitions: SchemaTransitionSet,
) -> None:
    if await initial_configuration_complete(session, transitions):
        return
    catalog = get_provider_profile("openrouter")
    if catalog is None:
        raise RuntimeError("The initial LLM configuration requires the OpenRouter bridge")
    provider = LLMProvider(
        name=catalog.display_name, catalog_code=catalog.code,
        provider_type=catalog.provider_type, base_url=catalog.base_url,
        api_key=None, configuration={}, is_active=True,
    )
    session.add(provider)
    await session.flush()
    models: dict[str, LLM] = {}
    for definition in INITIAL_MODELS:
        model = LLM(
            llm_provider_id=provider.id, code=definition.code,
            llm_name=definition.name, label=definition.label,
            resource_type="model", primary_capability=definition.capabilities[0],
            service_capabilities=list(definition.capabilities),
            context_length=definition.context_length,
        )
        for modality in ("text", "image", "file", "video", "audio"):
            setattr(model, f"input_{modality}", modality in definition.inputs)
            setattr(model, f"output_{modality}", modality in definition.outputs)
        session.add(model)
        models[definition.code] = model
    await session.flush()
    # Permanent datasets may have supplied the empty baseline after an earlier
    # failed attempt. Reuse it when the journal retries the unfinished action.
    profile = await session.scalar(select(LlmProfile).order_by(LlmProfile.id).limit(1))
    if profile is None:
        profile = LlmProfile(code=profile_code(DEFAULT_PROFILE_LABEL), label=DEFAULT_PROFILE_LABEL)
        session.add(profile)
    profile.text_ultra_low_reasoning_effort = "none"
    profile.text_low_reasoning_effort = "low"
    profile.text_standard_reasoning_effort = "medium"
    profile.text_high_reasoning_effort = "high"
    profile.decision_fallback_policy = "text_on_failure"
    for field, code in INITIAL_SELECTIONS.items():
        setattr(profile, field, models[code].id)
    await session.flush()
