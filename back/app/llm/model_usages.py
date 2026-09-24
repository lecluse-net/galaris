"""Canonical identifiers for the model fields stored on an LLM profile.

Text mechanisms share four explicit quality/cost tiers.  The semantic aliases
below keep call sites readable while making the usage-to-tier policy unique and
auditable in this module.  Specialized media and embedding usages retain their
own profile columns.
"""

TEXT_ULTRA_LOW = "text_ultra_low_llm_id"
TEXT_LOW = "text_low_llm_id"
TEXT_STANDARD = "text_standard_llm_id"
TEXT_HIGH = "text_high_llm_id"

TEXT_ULTRA_LOW_REASONING = "text_ultra_low_reasoning_effort"
TEXT_LOW_REASONING = "text_low_reasoning_effort"
TEXT_STANDARD_REASONING = "text_standard_reasoning_effort"
TEXT_HIGH_REASONING = "text_high_reasoning_effort"

DREAM = TEXT_ULTRA_LOW
DISPATCHER = TEXT_LOW
CONVERSATION = TEXT_LOW
BRIEFING = TEXT_STANDARD
EXECUTOR = TEXT_STANDARD
GOAL = TEXT_STANDARD
EXECUTOR_HIGH = TEXT_HIGH
PLANNER = TEXT_HIGH
LAB = TEXT_HIGH

VISION = "vision_llm_id"
DOCUMENT = "document_llm_id"
AUDIO = "audio_llm_id"
VIDEO = "video_llm_id"
SOUND_GENERATION = "sound_generation_llm_id"
MUSIC_GENERATION = "music_generation_llm_id"
VIDEO_GENERATION = "video_generation_llm_id"
IMAGE = "image_llm_id"
TRANSCRIPTION = "transcription_llm_id"
VECTOR = "vector_llm_id"
DECISION = "decision_llm_id"

TEXT_TIERS: tuple[str, ...] = (
    TEXT_ULTRA_LOW,
    TEXT_LOW,
    TEXT_STANDARD,
    TEXT_HIGH,
)

TEXT_REASONING_FIELDS: tuple[str, ...] = (
    TEXT_ULTRA_LOW_REASONING,
    TEXT_LOW_REASONING,
    TEXT_STANDARD_REASONING,
    TEXT_HIGH_REASONING,
)

_TEXT_REASONING_BY_TIER: dict[str, str] = dict(
    zip(TEXT_TIERS, TEXT_REASONING_FIELDS, strict=True)
)


def reasoning_field_for_text_tier(model_field: str) -> str | None:
    """Return the reasoning column paired with one text-model tier."""

    return _TEXT_REASONING_BY_TIER.get(model_field)

_TEXT_TIER_ALIASES: dict[str, str] = {
    "ultra-low": TEXT_ULTRA_LOW,
    "haiku": TEXT_ULTRA_LOW,
    "low": TEXT_LOW,
    "sonnet": TEXT_LOW,
    "luna": TEXT_LOW,
    "standard": TEXT_STANDARD,
    "opus": TEXT_STANDARD,
    "terra": TEXT_STANDARD,
    "high": TEXT_HIGH,
    "fable": TEXT_HIGH,
    "sol": TEXT_HIGH,
}


def text_tier_for_alias(value: str) -> str | None:
    """Resolve canonical and Claude/Codex family aliases to a text tier.

    A configured LLM code always takes precedence; proxy resolution calls this
    helper only after direct code lookup failed.  Token matching accepts stable
    family names such as ``claude-sonnet-5`` and ``gpt-5.6-terra``.
    """

    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    if not normalized:
        return None
    direct = _TEXT_TIER_ALIASES.get(normalized)
    if direct is not None:
        return direct
    for token in normalized.split("-"):
        if tier := _TEXT_TIER_ALIASES.get(token):
            return tier
    return None


ALL: tuple[str, ...] = (
    DECISION,
    *TEXT_TIERS,
    VISION,
    DOCUMENT,
    AUDIO,
    VIDEO,
    SOUND_GENERATION,
    MUSIC_GENERATION,
    VIDEO_GENERATION,
    IMAGE,
    TRANSCRIPTION,
    VECTOR,
)
