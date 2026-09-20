"""LLM configuration, execution, proxying, and tracing."""

from .embedding_events import register_embedding_change_listener
from .models import LLMCall
from .retention import prune_traces
from . import model_usages
from .profile_models import LlmProfile
from .provider_models import LLM, LLMProvider
from .purposes import LLMCallPurpose
from .provider_schemas import LLMProviderCreate, LLMProviderResponse, LLMProviderUpdate
from .provider_facade import (
    CHAT_PARAMETERS,
    RESPONSES_PARAMETERS,
    SAMPLING_PARAMETERS,
    RequestParameterPolicy,
    register_request_parameter_policy,
    compatible_parameter_policy,
    ImageDimensionsError,
    NativeImageSize,
    nearest_image_size,
    resolve_image_size,
    ImageGenerationResult,
    ManagedRuntimeCredential,
    PreparedChatRequest,
    ProviderConnection,
    ReasoningEffort,
    ResponsesOperation,
)
from . import (
    llm_call_service,
    llm_provider_service,
    llm_service,
    profile_service,
    transcription_service,
    tts_service,
)
from .llm_service import (
    MediaCaps,
    caps_for_llm,
    get_audio_llm,
    get_document_llm,
    get_image_llm,
    get_llm_for_agent,
    get_transcription_llm,
    get_video_llm,
    get_vision_llm,
)
from .correlation import llm_correlation_scope
from .native_media import normalized_media_type, supports_native_input
from .runtime_correlation import resolve_runtime_process_run_id
from .subscription_policy import llm_execution_scope
from .facade import (
    AgentRunUsage,
    aggregate_agent_run_usage,
    get_managed_runtime_credential,
)
from .embedding_facade import rank_texts_by_semantic_similarity
from .image_generation_service import generate_image_native
from .handlers import get_handler_for_url
from .structured_service import (
    StructuredOutputRetry,
    run_prompted,
    run_structured,
    reasoning_effort_scope,
)
from .events import register_events as _register_events

_register_events()


def register_scheduler_jobs() -> None:
    """Register LLM trace reconciliation in the durable Task scheduler."""

    from app.task import scheduler

    scheduler.register_periodic_job(
        "llm-running-call-reconciliation",
        llm_call_service.reconcile_stale_running_calls,
        interval=60.0,
    )


from .media_contracts import (
    MediaArtifact,
    MediaOperation,
    MediaProvider,
    MediaRequest,
    MediaResult,
    register_media_provider,
)
from .media_facade import available_media_functions, resolve_media_resource

from .retention import register_trace_release

__all__ = [
    "normalized_media_type", "supports_native_input",
    "CHAT_PARAMETERS",
    "RESPONSES_PARAMETERS",
    "SAMPLING_PARAMETERS",
    "RequestParameterPolicy",
    "register_request_parameter_policy",
    "compatible_parameter_policy",
    "register_trace_release",
    "register_embedding_change_listener",
    "prune_traces",
    "MediaArtifact",
    "MediaOperation",
    "MediaProvider",
    "MediaRequest",
    "MediaResult",
    "register_media_provider",
    "available_media_functions",
    "resolve_media_resource",
    "ImageDimensionsError",
    "NativeImageSize",
    "nearest_image_size",
    "resolve_image_size",
    "ImageGenerationResult",
    "generate_image_native",
    "AgentRunUsage",
    "LLM",
    "LLMCall",
    "LLMCallPurpose",
    "LLMProvider",
    "LLMProviderCreate",
    "LLMProviderResponse",
    "LLMProviderUpdate",
    "LlmProfile",
    "MediaCaps",
    "ManagedRuntimeCredential",
    "PreparedChatRequest",
    "ProviderConnection",
    "ReasoningEffort",
    "ResponsesOperation",
    "StructuredOutputRetry",
    "aggregate_agent_run_usage",
    "caps_for_llm",
    "get_audio_llm",
    "get_document_llm",
    "get_handler_for_url",
    "get_image_llm",
    "get_managed_runtime_credential",
    "get_llm_for_agent",
    "get_transcription_llm",
    "get_video_llm",
    "get_vision_llm",
    "llm_call_service",
    "llm_correlation_scope",
    "llm_execution_scope",
    "llm_provider_service",
    "llm_service",
    "model_usages",
    "profile_service",
    "rank_texts_by_semantic_similarity",
    "resolve_runtime_process_run_id",
    "run_prompted",
    "run_structured",
    "reasoning_effort_scope",
    "register_scheduler_jobs",
    "transcription_service",
    "tts_service",
]
