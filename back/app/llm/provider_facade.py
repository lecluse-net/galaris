"""Public extension points implemented by external AI-provider bridges."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Annotated, Any, Literal, Protocol, TypeAlias

import httpx
from .decision_contracts import ChoiceQuestion, DecisionUnavailable, ProviderDecisionResponse
from pydantic import BeforeValidator
from pydantic_ai.profiles import ModelProfile

from .capabilities import AICapability
from .handlers.base import LLMModelInfo
from .provider_catalog import ProviderProfile, register_provider_profile, resolve_provider_profile
from .request_parameters import (
    BASIC_PARAMETERS, CHAT_PARAMETERS, RESPONSES_PARAMETERS, SAMPLING_PARAMETERS,
    ParameterPolicyResolver, RequestParameterPolicy, RequestProtocol,
    adapt_request_parameters, compatible_parameter_policy,
)


def _legacy_reasoning_effort(value: object) -> object:
    return "low" if value == "minimal" else value


ReasoningEffort: TypeAlias = Annotated[
    Literal["none", "low", "medium", "high", "xhigh", "max"],
    BeforeValidator(_legacy_reasoning_effort),
]
ResponsesOperation = Literal["create", "compact"]
ResponsesReasoningContext = Literal["auto", "current_turn", "all_turns"]
ResponsesReasoningSummary = Literal["detailed", "concise", "auto"]


def _empty_configuration() -> dict[str, Any]:
    return {}


def _empty_usage() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    """Immutable provider configuration passed across the bridge boundary."""

    id: int | None
    name: str
    catalog_code: str | None
    provider_type: str
    base_url: str
    api_key: str | None = field(default=None, repr=False)
    configuration: dict[str, Any] = field(default_factory=_empty_configuration)


@dataclass(frozen=True, slots=True)
class ProviderResponsesPolicy:
    """Provider-owned compatibility contract for the internal Responses runtime."""

    model_profile: Callable[[str], ModelProfile | None]
    chat_fallback_statuses: frozenset[int] = frozenset()
    supports_compaction: bool = False
    store: bool | None = None
    reasoning_context: ResponsesReasoningContext | None = None
    reasoning_summary: ResponsesReasoningSummary | None = None
    send_reasoning_ids: bool | None = None


@dataclass(frozen=True, slots=True)
class ProviderMediaInputPolicy:
    """Native Chat wire formats supported by a provider, intersected with model flags."""

    audio_types: frozenset[str] = frozenset({"audio/wav", "audio/mpeg"})
    video_types: frozenset[str] = frozenset()


class ResourceDiscovery(Protocol):
    """Discover provider resources for one canonical capability."""

    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]: ...


class DecisionProvider(Protocol):
    async def decide(
        self, connection: ProviderConnection, *, model: str, state: str,
        questions: dict[str, ChoiceQuestion], timeout_seconds: float | None,
    ) -> ProviderDecisionResponse: ...


_decision_providers: dict[str, DecisionProvider] = {}


def register_decision_provider(code: str, service: DecisionProvider) -> None:
    _decision_providers[code] = service


def decision_provider_for(connection: ProviderConnection) -> DecisionProvider | None:
    profile = resolve_provider_profile(catalog_code=connection.catalog_code, base_url=connection.base_url)
    return _decision_providers.get(profile.code if profile else _service_key(connection) or "")


class ModelManagement(Protocol):
    """Install or delete provider-managed models."""

    async def pull_model(
        self,
        connection: ProviderConnection,
        model_name: str,
    ) -> str: ...

    async def delete_model(
        self,
        connection: ProviderConnection,
        model_name: str,
    ) -> str: ...


class ModelMetadata(Protocol):
    """Enrich one resource with metadata unavailable from generic registries."""

    async def get_model_metadata(
        self,
        connection: ProviderConnection,
        model_name: str,
    ) -> LLMModelInfo | None: ...


class ModelCatalogMetadata(Protocol):
    """Optional third-party metadata catalog for model enrichment."""

    async def enrich_models(
        self,
        connection: ProviderConnection,
        models: list[LLMModelInfo],
        *,
        force_refresh: bool = False,
    ) -> list[LLMModelInfo]: ...

    async def get_model_metadata(
        self,
        connection: ProviderConnection,
        model_name: str,
    ) -> LLMModelInfo | None: ...

    def clear_cache(self) -> None: ...


class ProviderUsageAccounting(Protocol):
    """Extract an exact inference cost from a provider-specific usage payload."""

    def inference_cost(self, usage: dict[str, Any]) -> float | None: ...


class ProviderTranscriptionError(RuntimeError):
    """Stable failure raised by transcription bridge implementations."""

    def __init__(self, message: str, *, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Normalized batch-transcription result, including billable provider usage."""

    text: str
    usage: dict[str, Any] = field(default_factory=_empty_usage)
    upstream_request_id: str | None = None
    raw_response: str = ""


@dataclass(frozen=True, slots=True)
class ImageGenerationResult:
    """Original provider image bytes and accounting information."""

    content: bytes
    media_type: str
    usage: dict[str, Any] = field(default_factory=_empty_usage)


class ImageDimensionsError(ValueError):
    """Model-safe explanation of unsupported or mismatched native image dimensions."""


@dataclass(frozen=True, slots=True)
class NativeImageSize:
    """Selected native pixels and their provider request options."""

    width: int | None
    height: int | None
    options: dict[str, str]


def nearest_image_size(
    width: int, height: int, candidates: Iterable[tuple[int, int]],
) -> tuple[int, int]:
    """Prefer the nearest size above the target, falling back below at model limits."""
    available = [
        (w, h) for w, h in candidates
        if 0 < w <= 8192 and 0 < h <= 8192 and w * h <= 33_554_432
    ]
    if not available:
        raise ImageDimensionsError("The model declares no supported native image sizes.")
    eligible = ((w, h) for w, h in available if w >= width and h >= height)
    # The common denominator width*height cancels from max(w/width, h/height).
    selected = min(eligible, key=lambda s: (
        max(s[0] * height, s[1] * width), s[0] * s[1], s[0], s[1],
    ), default=None)
    if selected is not None:
        return selected
    return min(available, key=lambda s: (
        max(abs(s[0] - width) * height, abs(s[1] - height) * width),
        abs(s[0] - width) * height + abs(s[1] - height) * width,
        -s[0] * s[1], s[0], s[1],
    ))


# Model authors own their dimension rules, including when a router serves the model.
_image_size_resolvers: dict[str, Callable[[str, int, int], NativeImageSize]] = {}


def register_image_size_resolver(
    namespace: str, resolver: Callable[[str, int, int], NativeImageSize],
) -> None:
    _image_size_resolvers[namespace] = resolver


def resolve_image_size(model: str, width: int, height: int) -> NativeImageSize:
    """Select native dimensions and request options for a routed model."""
    namespace, _, name = model.partition("/")
    resolver = _image_size_resolvers.get(namespace)
    if resolver is not None:
        return resolver(name.split(":", 1)[0], width, height)
    # Unknown routed models choose their own default rather than receiving an
    # arbitrary pixel size that a tier-based API could reject or normalize.
    return NativeImageSize(None, None, {})


class ImageGenerationProvider(Protocol):
    """Select native dimensions and translate them to the provider's image API."""

    def select_size(self, model: str, width: int, height: int) -> NativeImageSize: ...

    def prepare_request(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        prompt: str,
        sources: list[tuple[bytes, str]],
        width: int,
        height: int,
    ) -> httpx.Request: ...

    def read_response(self, response: httpx.Response) -> ImageGenerationResult: ...


class ProviderAuthenticationError(RuntimeError):
    """Safe authentication failure exposed by a provider bridge."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_authentication_error",
        status_code: int = 502,
        relogin_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.relogin_required = relogin_required


class ProviderAuthentication(Protocol):
    async def start_device_login(self, provider_id: int) -> dict[str, Any]: ...

    async def poll_device_login(
        self,
        provider_id: int,
        *,
        device_auth_id: str,
        user_code: str,
    ) -> dict[str, Any]: ...

    async def disconnect(self, provider_id: int) -> None: ...


@dataclass(frozen=True, slots=True)
class ProviderQuotaWindow:
    name: Literal["primary", "secondary"]
    used_percent: float
    window_seconds: int | None
    resets_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProviderQuota:
    windows: list[ProviderQuotaWindow]
    checked_at: datetime


class ProviderQuotaReader(Protocol):
    async def get_quota(self, provider_id: int) -> ProviderQuota: ...


@dataclass(frozen=True, slots=True)
class ManagedRuntimeCredential:
    """Short-lived provider credential delivered only to a managed runtime."""

    auth_mode: Literal["chatgpt"]
    secret: str = field(repr=False)
    account_id: str | None = None
    plan_type: str | None = None


class ManagedRuntimeAuthentication(Protocol):
    """Mint or refresh credentials for an isolated provider-owned runtime."""

    async def get_runtime_credential(
        self,
        provider_id: int,
    ) -> ManagedRuntimeCredential: ...


class ChatStreamAdapter(Protocol):
    response_id: str
    created: int
    model: str
    terminal: bool

    def convert(self, raw_event: dict[str, Any]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class PreparedChatRequest:
    endpoint: str
    headers: dict[str, str]
    body: dict[str, Any]


class ProviderChatTransport(Protocol):
    """Provider-specific adaptation around the canonical chat contract."""

    stream_only: bool

    async def prepare_request(
        self,
        provider_id: int,
        connection: ProviderConnection,
        body: dict[str, Any],
        *,
        force_refresh: bool = False,
        force_stream: bool = False,
    ) -> PreparedChatRequest: ...

    def normalize_response(
        self,
        payload: dict[str, Any],
        *,
        model: str,
    ) -> dict[str, Any]: ...

    def create_stream_adapter(self, model: str) -> ChatStreamAdapter | None: ...


class ProviderResponsesTransport(Protocol):
    """Provider-specific authentication for the native Responses contract."""

    async def prepare_responses_request(
        self,
        provider_id: int,
        connection: ProviderConnection,
        body: dict[str, Any],
        *,
        operation: ResponsesOperation = "create",
        force_refresh: bool = False,
    ) -> PreparedChatRequest: ...


class OpenAIProtocolAdapter(Protocol):
    """Provider-owned endpoint normalization for the canonical OpenAI protocol."""

    def base_url(self, connection: ProviderConnection) -> str: ...


@dataclass(frozen=True)
class ProviderRuntimePolicy:
    realtime_reasoning_effort: ReasoningEffort | None = None


class TranscriptionProvider(Protocol):
    """Provider-specific batch transcription implementation."""

    async def transcribe(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        source: bytes | Path,
        filename: str,
        mime_type: str,
        language: str,
        timeout: float,
    ) -> TranscriptionResult: ...


class RealtimeTranscriber(Protocol):
    """One live provider session fed while the caller is speaking."""

    async def send_audio(self, pcm: bytes) -> None: ...

    async def commit(self) -> str: ...

    async def close(self) -> None: ...


class RealtimeTranscriptionProvider(Protocol):
    """Provider-specific realtime transcription implementation."""

    async def create_realtime_transcriber(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        language: str,
        sample_rate: int,
        channels: int,
    ) -> RealtimeTranscriber | None: ...


@dataclass(frozen=True, slots=True)
class RealtimeToolDefinition:
    """Provider-neutral function exposed during a live multimodal session."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RealtimeConversationEvent:
    """Normalized provider event consumed by the voice orchestration layer."""

    kind: Literal[
        "session_ready",
        "speech_started",
        "input_committed",
        "response_started",
        "output_item",
        "audio_delta",
        "text_delta",
        "audio_transcript_delta",
        "function_call",
        "response_done",
        "response_cancelled",
        "error",
    ]
    audio: bytes = b""
    text: str = ""
    item_id: str = ""
    response_id: str = ""
    call_id: str = ""
    tool_name: str = ""
    arguments: str = ""
    error: str = ""


class RealtimeConversationSession(Protocol):
    """One stateful provider conversation over a live connection."""

    sample_rate: int
    channels: int

    async def send_audio(self, pcm: bytes) -> None: ...
    async def receive(self) -> RealtimeConversationEvent: ...
    async def send_function_output(self, call_id: str, output: str) -> None: ...
    async def request_response(self, instructions: str | None = None) -> None: ...
    async def cancel_response(self) -> None: ...
    async def truncate(self, item_id: str, audio_end_ms: int) -> None: ...
    async def close(self) -> None: ...


class RealtimeConversationProvider(Protocol):
    """Provider-specific low-latency audio conversation implementation."""

    async def create_realtime_session(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        voice: str | None,
        instructions: str,
        tools: tuple[RealtimeToolDefinition, ...],
        output_audio: bool,
    ) -> RealtimeConversationSession: ...


@dataclass(frozen=True)
class SpeechOptions:
    """Provider-neutral controls for speech synthesis."""

    voice: str = ""
    model: str = ""
    language: str = ""
    speed: float = 1.0
    pitch: float = 0.0
    stability: float | None = None
    similarity_boost: float | None = None
    style: float | None = None
    use_speaker_boost: bool | None = None


@dataclass(frozen=True)
class SpeechResult:
    content: bytes
    provider_name: str
    voice: str


class RealtimeSpeechStream(Protocol):
    sample_rate: int
    channels: int

    def stream(self, segments: AsyncIterator[str]) -> AsyncIterator[bytes]: ...


class SpeechProvider(Protocol):
    """Provider-specific speech synthesis implementation."""

    async def synthesize(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        text: str,
        options: SpeechOptions,
    ) -> SpeechResult: ...

    async def create_realtime_stream(
        self,
        connection: ProviderConnection,
        *,
        model: str,
        resource_type: str,
        options: SpeechOptions,
    ) -> RealtimeSpeechStream | None: ...


_resource_discovery: dict[str, ResourceDiscovery] = {}
_model_management: dict[str, ModelManagement] = {}
_model_metadata: dict[str, ModelMetadata] = {}
_model_catalog_metadata: ModelCatalogMetadata | None = None
_transcription: dict[str, TranscriptionProvider] = {}
_image_generation: dict[str, ImageGenerationProvider] = {}
_realtime_transcription: dict[str, RealtimeTranscriptionProvider] = {}
_realtime_conversation: dict[str, RealtimeConversationProvider] = {}
_speech: dict[str, SpeechProvider] = {}
_authentication: dict[str, ProviderAuthentication] = {}
_quota_readers: dict[str, ProviderQuotaReader] = {}
_managed_runtime_authentication: dict[str, ManagedRuntimeAuthentication] = {}
_chat_transport: dict[str, ProviderChatTransport] = {}
_responses_transport: dict[str, ProviderResponsesTransport] = {}
_responses_policy: dict[str, ProviderResponsesPolicy] = {}
_openai_protocol: dict[str, OpenAIProtocolAdapter] = {}
_runtime_policy: dict[str, ProviderRuntimePolicy] = {}
_usage_accounting: dict[str, ProviderUsageAccounting] = {}
_parameter_policies: dict[str, ParameterPolicyResolver] = {}
_media_input_policies: dict[str, ProviderMediaInputPolicy] = {}


def register_media_input_policy(code: str, policy: ProviderMediaInputPolicy) -> None:
    _media_input_policies[code] = policy


def media_input_policy_for(connection: ProviderConnection) -> ProviderMediaInputPolicy:
    profile = resolve_provider_profile(catalog_code=connection.catalog_code, base_url=connection.base_url)
    key = profile.code if profile is not None else _service_key(connection)
    return _media_input_policies.get(key or "", ProviderMediaInputPolicy())


def register_request_parameter_policy(code: str, resolver: ParameterPolicyResolver) -> None:
    _parameter_policies[code] = resolver


def request_parameter_policy_for(connection: ProviderConnection, model: str) -> RequestParameterPolicy:
    profile = resolve_provider_profile(catalog_code=connection.catalog_code, base_url=connection.base_url)
    key = profile.code if profile is not None else _service_key(connection)
    resolver = _parameter_policies.get(key) if key else None
    if profile is not None and resolver is None:
        raise ValueError(f"Provider {profile.code!r} has no request parameter policy.")
    return resolver(model) if resolver else compatible_parameter_policy()


def register_provider(profile: ProviderProfile) -> None:
    """Register the immutable product profile owned by a bridge."""

    register_provider_profile(profile)


def register_resource_discovery(code: str, service: ResourceDiscovery) -> None:
    _resource_discovery[code] = service


def register_model_management(code: str, service: ModelManagement) -> None:
    _model_management[code] = service


def register_model_metadata(code: str, service: ModelMetadata) -> None:
    _model_metadata[code] = service


def register_model_catalog_metadata(service: ModelCatalogMetadata) -> None:
    global _model_catalog_metadata
    _model_catalog_metadata = service


def model_catalog_metadata() -> ModelCatalogMetadata | None:
    return _model_catalog_metadata


def register_transcription_provider(
    code: str,
    service: TranscriptionProvider,
) -> None:
    _transcription[code] = service


def register_image_generation_provider(code: str, service: ImageGenerationProvider) -> None:
    _image_generation[code] = service


def image_generation_provider_for(connection: ProviderConnection) -> ImageGenerationProvider | None:
    profile = resolve_provider_profile(catalog_code=connection.catalog_code, base_url=connection.base_url)
    if profile is not None:
        return _image_generation.get(profile.code)
    key = _service_key(connection)
    if key:
        return _image_generation.get(key)
    return _image_generation.get(connection.provider_type)


def register_realtime_transcription_provider(
    code: str,
    service: RealtimeTranscriptionProvider,
) -> None:
    _realtime_transcription[code] = service


def register_realtime_conversation_provider(
    code: str,
    service: RealtimeConversationProvider,
) -> None:
    _realtime_conversation[code] = service


def register_speech_provider(code: str, service: SpeechProvider) -> None:
    _speech[code] = service


def register_provider_authentication(
    code: str,
    service: ProviderAuthentication,
) -> None:
    _authentication[code] = service


def register_provider_quota_reader(code: str, service: ProviderQuotaReader) -> None:
    _quota_readers[code] = service


def provider_quota_reader_for(connection: ProviderConnection) -> ProviderQuotaReader | None:
    key = _service_key(connection)
    return _quota_readers.get(key) if key else None


def register_managed_runtime_authentication(
    code: str,
    service: ManagedRuntimeAuthentication,
) -> None:
    _managed_runtime_authentication[code] = service


def register_chat_transport(code: str, service: ProviderChatTransport) -> None:
    _chat_transport[code] = service


def register_responses_transport(
    code: str,
    service: ProviderResponsesTransport,
) -> None:
    _responses_transport[code] = service


def register_responses_policy(
    code: str,
    policy: ProviderResponsesPolicy,
) -> None:
    """Register model-level Responses compatibility for one provider bridge."""

    _responses_policy[code] = policy


def register_openai_protocol_adapter(
    code: str,
    service: OpenAIProtocolAdapter,
) -> None:
    _openai_protocol[code] = service


def register_runtime_policy(code: str, policy: ProviderRuntimePolicy) -> None:
    _runtime_policy[code] = policy


def register_usage_accounting(
    code: str,
    service: ProviderUsageAccounting,
) -> None:
    _usage_accounting[code] = service


def _service_key(connection: ProviderConnection) -> str | None:
    return connection.catalog_code or (
        connection.provider_type if connection.provider_type != "openai_compatible" else None
    )


def resource_discovery_for(
    connection: ProviderConnection,
) -> ResourceDiscovery | None:
    key = _service_key(connection)
    return _resource_discovery.get(key) if key else None


def model_management_for(
    connection: ProviderConnection,
) -> ModelManagement | None:
    key = _service_key(connection)
    return _model_management.get(key) if key else None


def model_metadata_for(
    connection: ProviderConnection,
) -> ModelMetadata | None:
    key = _service_key(connection)
    return _model_metadata.get(key) if key else None


def transcription_provider_for(
    connection: ProviderConnection,
) -> TranscriptionProvider | None:
    key = _service_key(connection)
    return _transcription.get(key) if key else None


def realtime_transcription_provider_for(
    connection: ProviderConnection,
) -> RealtimeTranscriptionProvider | None:
    key = _service_key(connection)
    return _realtime_transcription.get(key) if key else None


def realtime_conversation_provider_for(
    connection: ProviderConnection,
) -> RealtimeConversationProvider | None:
    key = _service_key(connection)
    return _realtime_conversation.get(key) if key else None


def speech_provider_for(
    connection: ProviderConnection,
) -> SpeechProvider | None:
    key = _service_key(connection)
    return _speech.get(key) if key else None


def provider_authentication_for(
    connection: ProviderConnection,
) -> ProviderAuthentication | None:
    key = _service_key(connection)
    return _authentication.get(key) if key else None


def managed_runtime_authentication_for(
    connection: ProviderConnection,
) -> ManagedRuntimeAuthentication | None:
    key = _service_key(connection)
    return _managed_runtime_authentication.get(key) if key else None


def chat_transport_for(
    connection: ProviderConnection,
) -> ProviderChatTransport | None:
    key = _service_key(connection)
    return _chat_transport.get(key) if key else None


def responses_transport_for(
    connection: ProviderConnection,
) -> ProviderResponsesTransport | None:
    key = _service_key(connection)
    return _responses_transport.get(key) if key else None


def responses_policy_for(
    connection: ProviderConnection,
) -> ProviderResponsesPolicy | None:
    key = _service_key(connection)
    return _responses_policy.get(key) if key else None


def openai_protocol_base_url(connection: ProviderConnection) -> str:
    """Return the canonical endpoint, optionally normalized by a bridge."""

    key = _service_key(connection)
    adapter = _openai_protocol.get(key) if key else None
    if adapter is not None:
        return adapter.base_url(connection).rstrip("/")
    return connection.base_url.rstrip("/")


def runtime_policy_for(
    connection: ProviderConnection,
) -> ProviderRuntimePolicy:
    key = _service_key(connection)
    return _runtime_policy.get(key, ProviderRuntimePolicy()) if key else ProviderRuntimePolicy()


def usage_accounting_for(code: str | None) -> ProviderUsageAccounting | None:
    """Return provider-owned accounting for a persisted catalog code."""

    return _usage_accounting.get(code) if code else None


__all__ = [
    "ProviderQuota", "ProviderQuotaWindow", "ProviderQuotaReader",
    "register_provider_quota_reader", "provider_quota_reader_for",
    "ChoiceQuestion", "DecisionUnavailable", "ProviderDecisionResponse", "DecisionProvider",
    "register_decision_provider", "decision_provider_for",
    "ProviderMediaInputPolicy", "register_media_input_policy", "media_input_policy_for",
    "BASIC_PARAMETERS", "CHAT_PARAMETERS", "RESPONSES_PARAMETERS", "SAMPLING_PARAMETERS",
    "RequestParameterPolicy", "RequestProtocol", "ParameterPolicyResolver",
    "adapt_request_parameters", "register_request_parameter_policy", "request_parameter_policy_for",
    "compatible_parameter_policy",
    "NativeImageSize",
    "nearest_image_size",
    "ImageDimensionsError",
    "register_image_size_resolver",
    "resolve_image_size",
    "ImageGenerationProvider",
    "ImageGenerationResult",
    "image_generation_provider_for",
    "register_image_generation_provider",
    "ChatStreamAdapter",
    "ManagedRuntimeAuthentication",
    "ManagedRuntimeCredential",
    "ModelManagement",
    "ModelCatalogMetadata",
    "ModelMetadata",
    "OpenAIProtocolAdapter",
    "ProviderConnection",
    "PreparedChatRequest",
    "ProviderAuthentication",
    "ProviderAuthenticationError",
    "ProviderChatTransport",
    "ProviderResponsesTransport",
    "ProviderResponsesPolicy",
    "ProviderTranscriptionError",
    "ProviderRuntimePolicy",
    "ResponsesOperation",
    "ProviderUsageAccounting",
    "RealtimeTranscriber",
    "RealtimeTranscriptionProvider",
    "RealtimeConversationEvent",
    "RealtimeConversationProvider",
    "RealtimeConversationSession",
    "RealtimeToolDefinition",
    "ResourceDiscovery",
    "RealtimeSpeechStream",
    "SpeechOptions",
    "SpeechProvider",
    "SpeechResult",
    "TranscriptionProvider",
    "TranscriptionResult",
    "chat_transport_for",
    "model_management_for",
    "model_catalog_metadata",
    "model_metadata_for",
    "managed_runtime_authentication_for",
    "openai_protocol_base_url",
    "provider_authentication_for",
    "register_chat_transport",
    "register_responses_transport",
    "register_responses_policy",
    "register_model_management",
    "register_model_catalog_metadata",
    "register_model_metadata",
    "register_managed_runtime_authentication",
    "register_openai_protocol_adapter",
    "register_provider",
    "register_provider_authentication",
    "register_runtime_policy",
    "register_usage_accounting",
    "register_realtime_transcription_provider",
    "register_realtime_conversation_provider",
    "register_resource_discovery",
    "register_speech_provider",
    "register_transcription_provider",
    "resource_discovery_for",
    "responses_transport_for",
    "responses_policy_for",
    "runtime_policy_for",
    "realtime_transcription_provider_for",
    "realtime_conversation_provider_for",
    "speech_provider_for",
    "transcription_provider_for",
    "usage_accounting_for",
]
