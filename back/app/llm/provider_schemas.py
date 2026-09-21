"""Schemas for provider catalog entries, connections, and configured LLMs."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime

from .capabilities import AICapability, AIResourceType
from .provider_catalog import ProviderType


# =============================================================================
# Provider schemas
# =============================================================================

class LLMProviderBase(BaseModel):
    """Base schema for a persisted provider connection."""
    name: str
    catalog_code: Optional[str] = None
    provider_type: ProviderType = "openai_compatible"
    base_url: str
    transcription_base_url: Optional[str] = None
    api_key: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class LLMProviderCreate(BaseModel):
    """Custom or backward-compatible provider creation schema."""
    name: str
    catalog_code: Optional[str] = None
    provider_type: ProviderType = "openai_compatible"
    base_url: str
    transcription_base_url: Optional[str] = None
    api_key: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    user_id: Optional[int] = None
    subscription_acknowledged: bool = False


class LLMProviderUpdate(BaseModel):
    """Provider update schema."""
    name: Optional[str] = None
    provider_type: Optional[ProviderType] = None
    base_url: Optional[str] = None
    transcription_base_url: Optional[str] = None
    api_key: Optional[str] = None
    configuration: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    user_id: Optional[int] = None
    subscription_acknowledged: bool = False


class LLMProviderResponse(BaseModel):
    """Provider response without its API key."""
    id: int
    name: str
    catalog_code: Optional[str] = None
    provider_type: ProviderType
    base_url: str
    transcription_base_url: Optional[str] = None
    api_key_configured: bool
    oauth_connected: bool
    user_id: Optional[int] = None
    subscription_acknowledged: bool = False
    configuration: Dict[str, Any]
    is_custom: bool
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LLMProviderDetailResponse(BaseModel):
    """Detailed provider response without exposing stored credentials."""
    id: int
    name: str
    catalog_code: Optional[str] = None
    provider_type: ProviderType
    base_url: str
    transcription_base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_configured: bool
    oauth_connected: bool
    user_id: Optional[int] = None
    subscription_acknowledged: bool = False
    configuration: Dict[str, Any]
    is_custom: bool
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProviderCatalogConfigure(BaseModel):
    """Create or update the connection associated with a built-in profile."""

    api_key: Optional[str] = None
    is_active: bool = True
    configuration: Dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[int] = None
    subscription_acknowledged: bool = False

    model_config = ConfigDict(extra="forbid")


class ProviderConfigurationFieldResponse(BaseModel):
    """Non-secret configuration field rendered by the provider form."""

    key: str
    label: str
    required: bool = False
    placeholder: Optional[str] = None


class ProviderCatalogItem(BaseModel):
    """Built-in profile or custom connection displayed in the provider picker."""

    key: str
    code: Optional[str] = None
    display_name: str
    provider_type: ProviderType
    auth_type: Literal["api_key", "oauth_device", "optional_api_key"]
    default_base_url: str
    token_url: Optional[str] = None
    documentation_url: Optional[str] = None
    icon: str
    color: str
    api_key_required: bool
    supports_transcription: bool
    capabilities: List[AICapability]
    configuration_fields: List[ProviderConfigurationFieldResponse] = Field(
        default_factory=lambda: list[ProviderConfigurationFieldResponse]()
    )
    supports_model_management: bool
    is_custom: bool
    connection: Optional[LLMProviderResponse] = None


class ProviderUserOption(BaseModel):
    """Minimal active-user projection for assigning a subscription owner."""

    id: int
    label: str


def _empty_provider_users() -> List[ProviderUserOption]:
    return []


class ProviderCatalogResponse(BaseModel):
    """Complete provider picker payload."""

    items: List[ProviderCatalogItem]
    users: List[ProviderUserOption] = Field(default_factory=_empty_provider_users)
    active_user_count: int = 0


class ProviderDeviceStartResponse(BaseModel):
    """Device-login challenge returned by a provider bridge."""
    verification_uri: str
    user_code: str
    device_auth_id: str
    interval: int
    expires_in: int


class ProviderDevicePollRequest(BaseModel):
    """Device-login values required while waiting for browser authorization."""
    device_auth_id: str
    user_code: str


class ProviderDevicePollResponse(BaseModel):
    """Current device-login state."""
    status: Literal["pending", "connected"]
    oauth_connected: bool


# =============================================================================
# Connection-test schemas
# =============================================================================

class LLMProviderTestRequest(BaseModel):
    """Request to test an LLM provider connection."""
    provider_id: Optional[int] = None
    base_url: str
    api_key: Optional[str] = None
    provider_type: ProviderType = "openai_compatible"
    catalog_code: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)


class LLMProviderTestResponse(BaseModel):
    """Connection-test response."""
    success: bool
    message: str
    provider_name: Optional[str] = None
    models_count: Optional[int] = None
    error_details: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# LLM model schemas
# =============================================================================

class LLMModalities(BaseModel):
    """Modalities supported by a model in each input and output direction.

    Five content types across two directions produce ten capability flags.
    """
    input_text: bool = True
    input_image: bool = False
    input_file: bool = False
    input_video: bool = False
    input_audio: bool = False
    output_text: bool = True
    output_image: bool = False
    output_file: bool = False
    output_video: bool = False
    output_audio: bool = False


class LLMModelInfo(BaseModel):
    """Information about an available AI model or voice."""
    id: str  # Technical model identifier.
    name: Optional[str] = None  # Display name.
    description: Optional[str] = None
    context_length: Optional[int] = None  # Context size in tokens.
    pricing: Optional[Dict[str, Any]] = None  # Input and output token prices.
    modalities: Optional["LLMModalities"] = None  # Provider-reported I/O capabilities.
    known_modalities: List[str] = Field(default_factory=list)
    capabilities: Optional[Dict[str, bool]] = None
    release_date: Optional[str] = None
    status: Optional[str] = None
    metadata_source: Optional[str] = None
    resource_type: AIResourceType = "model"
    service_capabilities: List[AICapability] = Field(
        default_factory=lambda: list[AICapability]()
    )

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Availability-check schemas
# =============================================================================

class LLMCheckRequest(BaseModel):
    """Request to check whether an LLM is available."""
    llm_provider_id: int
    llm_name: str


class LLMCheckResponse(BaseModel):
    """LLM availability response."""
    llm_provider_id: int
    llm_name: str
    available: bool
    provider_name: str
    message: str

    model_config = ConfigDict(from_attributes=True)


class LLMBatchCheckResponse(BaseModel):
    """Batch availability response for configured LLMs."""
    results: List[LLMCheckResponse]
    total: int
    available_count: int
    unavailable_count: int

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Configured LLM schemas
# =============================================================================

class LLMBase(BaseModel):
    """Base schema for a configured LLM."""
    llm_provider_id: int
    code: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
    llm_name: str
    label: str


class LLMCreate(BaseModel):
    """Configured LLM creation schema.

    Optional modality values are resolved from the provider when possible, otherwise text-only
    defaults apply.
    """
    llm_provider_id: int
    code: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
    llm_name: str
    label: str
    resource_type: AIResourceType = "model"
    primary_capability: AICapability = "chat"
    service_capabilities: List[AICapability] = Field(
        default_factory=lambda: list[AICapability]()
    )
    pricing: Dict[str, Any] = Field(default_factory=dict)
    context_length: Optional[int] = Field(default=None, gt=0)
    cost_per_input_token: Optional[float] = None
    cost_per_cached_input_token: Optional[float] = None
    cost_per_output_token: Optional[float] = None
    is_subscription: bool = False
    input_text: Optional[bool] = None
    input_image: Optional[bool] = None
    input_file: Optional[bool] = None
    input_video: Optional[bool] = None
    input_audio: Optional[bool] = None
    output_text: Optional[bool] = None
    output_image: Optional[bool] = None
    output_file: Optional[bool] = None
    output_video: Optional[bool] = None
    output_audio: Optional[bool] = None


class LLMUpdate(BaseModel):
    """Configured LLM update schema."""
    llm_provider_id: Optional[int] = None
    code: Optional[str] = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$")
    llm_name: Optional[str] = None
    label: Optional[str] = None
    resource_type: Optional[AIResourceType] = None
    primary_capability: Optional[AICapability] = None
    service_capabilities: Optional[List[AICapability]] = None
    pricing: Optional[Dict[str, Any]] = None
    context_length: Optional[int] = Field(default=None, gt=0)
    cost_per_input_token: Optional[float] = None
    cost_per_cached_input_token: Optional[float] = None
    cost_per_output_token: Optional[float] = None
    is_subscription: Optional[bool] = None
    input_text: Optional[bool] = None
    input_image: Optional[bool] = None
    input_file: Optional[bool] = None
    input_video: Optional[bool] = None
    input_audio: Optional[bool] = None
    output_text: Optional[bool] = None
    output_image: Optional[bool] = None
    output_file: Optional[bool] = None
    output_video: Optional[bool] = None
    output_audio: Optional[bool] = None


class LLMResponse(LLMModalities):
    """Configured LLM response."""
    id: int
    llm_provider_id: int
    code: str
    llm_name: str
    label: str
    resource_type: AIResourceType
    primary_capability: AICapability
    service_capabilities: List[AICapability]
    pricing: Dict[str, Any]
    context_length: Optional[int] = None
    cost_per_input_token: Optional[float] = None
    cost_per_cached_input_token: Optional[float] = None
    cost_per_output_token: Optional[float] = None
    is_subscription: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LLMWithProviderResponse(LLMResponse):
    """Configured LLM response enriched with provider information."""
    provider_name: str


class LLMModelsListResponse(BaseModel):
    """Response containing available provider models."""
    provider_id: Optional[int] = None
    provider_name: str
    models: List[LLMModelInfo]
    count: int
    supports_model_management: bool = False
    capability: AICapability = "chat"

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Model-management schemas
# =============================================================================

class ModelManageRequest(BaseModel):
    """Request to install or delete a provider model."""
    model_name: str


class ModelManageResponse(BaseModel):
    """Response from a model-management operation."""
    success: bool
    message: str
    model_name: str
    provider_id: int
    provider_name: str

    model_config = ConfigDict(from_attributes=True)
