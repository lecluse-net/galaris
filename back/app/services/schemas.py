"""Pydantic schemas for Galaris Services and their exposed functions."""

from datetime import datetime
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from .rest_contracts import RestConfig
from .protocols import ProtocolConfig
from .capabilities import validate_capabilities
from .naming import validate_custom_service_name
from .service_icons import ServiceIcon


class ServiceCatalogMetadata(BaseModel):
    """Provenance retained on a local copy, never an automatic update policy."""
    format_version: int = Field(default=1, ge=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    minimum_galaris_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    summary: dict[str, str] = Field(default_factory=dict)
    documentation: str = Field(default="", max_length=2048)
    icon_credit: str = Field(default="", max_length=1024)
    plugin_code: str | None = Field(default=None, max_length=100)
    plugin_version: str | None = Field(default=None, max_length=32)


# =============================================================================
# MCP configuration
# =============================================================================

McpAuthType = Literal["oauth", "bearer", "header", "basic", "none"]


class McpAuth(BaseModel):
    """Authentication configuration for an MCP server."""
    type: McpAuthType = "none"

    # Header name for custom-header authentication.
    header_name: str = "Authorization"

    # Key used to resolve the token from connection parameters.
    param: Optional[str] = None
    # Basic-auth login and password parameter names.
    login_param: str = "login"
    password_param: str = "password"

    # Static fallback token.
    token_static: Optional[str] = None

    # Optional query-string parameter name.
    url_param: Optional[str] = None


class McpConfig(BaseModel):
    """Complete MCP server configuration."""
    type: Literal["sse", "http", "stdio"]

    # SSE / HTTP
    url: Optional[str] = None

    # stdio
    command: Optional[str] = None
    args: List[str] = Field(default_factory=lambda: [])
    env: Dict[str, str] = Field(default_factory=lambda: {})

    # Additional static HTTP headers merged with authentication headers.
    headers: Dict[str, str] = Field(default_factory=lambda: {})

    auth: McpAuth = Field(default_factory=McpAuth)
    timeout: int = 120

    @model_validator(mode="after")
    def oauth_requires_http(self) -> "McpConfig":
        if self.type == "stdio" and self.auth.type == "oauth":
            raise ValueError("MCP OAuth requires HTTP or SSE")
        return self

class McpAuthPublic(BaseModel):
    """Read model exposing credential presence but never its value."""

    type: McpAuthType = "none"
    header_name: str = "Authorization"
    param: Optional[str] = None
    login_param: str = "login"
    password_param: str = "password"
    url_param: Optional[str] = None
    token_static_configured: bool = False


class McpConfigPublic(BaseModel):
    """Public MCP configuration with write-only literal mapping values."""

    type: Literal["sse", "http", "stdio"]
    url: Optional[str] = None
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)
    auth: McpAuthPublic = Field(default_factory=McpAuthPublic)
    timeout: int = 120


class FileShareConfig(BaseModel):
    """Bridge-driven file-sharing service configuration."""
    service: str
    base_url: str

    # Bridge parameter key to connection parameter name.
    param_map: Dict[str, str] = Field(default_factory=lambda: {})


class MessengerConfig(BaseModel):
    """Bridge-driven messaging service configuration."""

    service: str

    # Server-level values shared by every agent connection to this Service.
    settings: Dict[str, str] = Field(default_factory=lambda: {})

    # Bridge parameter key to connection parameter name.
    param_map: Dict[str, str] = Field(default_factory=lambda: {})


class ListenerConfig(BaseModel):
    """Webhook-listener configuration for a tool."""
    url: Optional[str] = None
    token: Optional[str] = None
    connection_key: str


class ListenerConfigPublic(BaseModel):
    """Listener metadata without the legacy static token."""

    url: Optional[str] = None
    connection_key: str
    token_configured: bool = False


# =============================================================================
# Connection schema.
# =============================================================================

class ConnectionParamOption(BaseModel):
    """A fixed choice: the stored value is independent of its display label."""

    value: str = Field(min_length=1)
    label: str = ""


class ConnectionParamDef(BaseModel):
    """Connection parameter definition."""
    type: str = "string"  # "string", "integer", "password", "boolean"
    widget: str = ""
    required: bool = True
    default: str = ""
    description: str = ""
    order: int | None = None
    label: str = ""
    builtin: bool = False
    options: list[ConnectionParamOption] = Field(default_factory=lambda: list[ConnectionParamOption]())

    @model_validator(mode="after")
    def validate_options(self) -> "ConnectionParamDef":
        if not self.options:
            return self
        if self.type not in {"string", "integer"}:
            raise ValueError("Fixed options require a string or integer parameter")
        values = [option.value for option in self.options]
        if len(set(values)) != len(values):
            raise ValueError("Fixed option values must be unique")
        if any(not value.strip() for value in values):
            raise ValueError("Fixed option values must not be blank")
        if self.type == "integer":
            for value in values:
                try:
                    int(value)
                except ValueError:
                    raise ValueError("Fixed options for an integer must contain integers") from None
        if self.default and self.default not in values:
            raise ValueError("The default must be one of the fixed options")
        return self


class ConnectionSchema(BaseModel):
    """Connection parameters keyed by name."""
    params: Dict[str, ConnectionParamDef] = Field(default_factory=lambda: {})


class ServiceGlobalParamPublic(BaseModel):
    """Safe global parameter projection; secret literals are write-only."""

    value: Optional[str] = None
    configured: bool = False
    secret: bool = False
    forced: bool = False


class ServiceGlobalParamUpdate(BaseModel):
    """One global parameter write.

    ``clear`` is explicit so an omitted password can preserve the existing encrypted value.
    """

    value: Optional[str] = None
    forced: bool = False
    clear: bool = False


class ServiceGlobalParamsUpdate(BaseModel):
    params: Dict[str, ServiceGlobalParamUpdate] = Field(default_factory=dict)


class ServiceGlobalParamsResponse(BaseModel):
    service_id: int
    params: Dict[str, ServiceGlobalParamPublic] = Field(default_factory=dict)


# =============================================================================
# Task configuration.
# =============================================================================

class TaskConfig(BaseModel):
    """Task template with runtime ``${...}`` substitution."""
    label: Optional[str] = None
    objective: Optional[str] = None

    def render(self, variables: Dict[str, object]) -> "TaskConfig":
        """Return a new configuration with variables replaced from the mapping."""
        import re
        import json

        def replace_vars(text: Optional[str]) -> Optional[str]:
            if text is None:
                return None

            def replacer(match: re.Match[str]) -> str:
                value = variables.get(match.group(1), match.group(0))
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)
                return str(value)

            return re.sub(r'\$\{([^}]+)\}', replacer, text)

        return TaskConfig(
            label=replace_vars(self.label),
            objective=replace_vars(self.objective),
        )


# =============================================================================
# Database-read tool models.
# =============================================================================

class ServiceBase(BaseModel):
    code: str
    label: str
    description: str = ""
    icon: ServiceIcon | None = None
    catalog: ServiceCatalogMetadata | None = None
    capabilities: list[str] | None = None
    _validate_capabilities = field_validator("capabilities")(validate_capabilities)
    mcp_config: Optional[McpConfig] = None
    rest_config: RestConfig | None = None
    file_share_config: Optional[FileShareConfig] = None
    messenger_config: Optional[MessengerConfig] = None
    listener_config: Optional[ListenerConfig] = None
    mail_config: ProtocolConfig | None = None
    calendar_config: ProtocolConfig | None = None
    connection_schema: ConnectionSchema = Field(default_factory=ConnectionSchema)
    task_config: Optional[TaskConfig] = None


class ServiceCreate(ServiceBase):
    _validate_names = field_validator("code", "label")(validate_custom_service_name)


class ServiceUpdate(BaseModel):
    icon: ServiceIcon | None = None
    catalog: ServiceCatalogMetadata | None = None
    capabilities: list[str] | None = None
    _validate_capabilities = field_validator("capabilities")(validate_capabilities)
    label: Optional[str] = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        return validate_custom_service_name(value) if value is not None else None

    description: Optional[str] = None
    mcp_config: Optional[McpConfig] = None
    expected_mcp_auth_type: McpAuthType | None = None
    rest_config: RestConfig | None = None
    file_share_config: Optional[FileShareConfig] = None
    messenger_config: Optional[MessengerConfig] = None
    listener_config: Optional[ListenerConfig] = None
    mail_config: ProtocolConfig | None = None
    calendar_config: ProtocolConfig | None = None
    connection_schema: Optional[ConnectionSchema] = None
    task_config: Optional[TaskConfig] = None


class ServiceRead(ServiceBase):
    id: int
    can_disable: bool = True
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def has_api(self) -> bool:
        return self.rest_config is not None

    @computed_field
    @property
    def has_mcp(self) -> bool:
        return self.mcp_config is not None

    @computed_field
    @property
    def has_file_share(self) -> bool:
        return self.file_share_config is not None

    @computed_field
    @property
    def has_messenger(self) -> bool:
        return self.messenger_config is not None

    @computed_field
    @property
    def has_listener(self) -> bool:
        return self.listener_config is not None

    @computed_field
    @property
    def has_mail(self) -> bool:
        return self.mail_config is not None

    @computed_field
    @property
    def has_calendar(self) -> bool:
        return self.calendar_config is not None

    @computed_field
    @property
    def can_edit(self) -> bool:
        from .assertions import service_can_edit

        return service_can_edit(self.code)

    model_config = {"from_attributes": True}


class ServicePublic(BaseModel):
    icon: ServiceIcon | None = None
    catalog: ServiceCatalogMetadata | None = None
    """Public API representation without static tokens."""
    id: int
    code: str
    label: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    has_mcp: bool
    has_api: bool = False
    rest_config: RestConfig | None = None
    has_file_share: bool
    has_messenger: bool
    has_listener: bool
    has_mail: bool = False
    has_calendar: bool = False
    can_edit: bool
    can_disable: bool = True
    mcp_config: Optional[McpConfigPublic] = None
    file_share_config: Optional[FileShareConfig] = None
    messenger_config: Optional[MessengerConfig] = None
    listener_config: Optional[ListenerConfigPublic] = None
    mail_config: ProtocolConfig | None = None
    calendar_config: ProtocolConfig | None = None
    connection_schema: ConnectionSchema
    global_params: Dict[str, ServiceGlobalParamPublic] = Field(default_factory=dict)
    task_config: Optional[TaskConfig] = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def has_function_permissions(self) -> bool:
        from .mcp_loader import has_function_permissions
        return has_function_permissions(self)

    model_config = {"from_attributes": True}


class ServiceListItem(ServicePublic):
    """Service catalogue entry with its existing active and inactive connections."""

    connection_count: int = Field(ge=0)


class McpToolFunctionPublic(BaseModel):
    """MCP function exposed by an application tool."""

    name: str
    description: str = ""
    enabled: bool = False


class ServiceMcpCatalogPublic(BaseModel):
    """Application tool MCP catalog for an agent."""

    service_id: int
    service_code: str
    service_label: str
    service_description: str = ""
    connection_id: Optional[int] = None
    mail_address: str = ""
    active: bool = False
    source: Literal["native", "external", "mixed"]
    runtime: str
    error: str = ""
    mcp_tools: List[McpToolFunctionPublic] = Field(
        default_factory=list[McpToolFunctionPublic]
    )


# =============================================================================
# Non-persistent MCP connection test.
# =============================================================================

class ServiceMcpTestRequest(BaseModel):
    """Preview an MCP configuration without persisting the Service."""

    service_id: Optional[int] = None
    code: str
    mcp_config: McpConfig
    params: Dict[str, Optional[str]] = Field(default_factory=dict)


class ServiceMcpTestFunction(BaseModel):
    """Function discovered while testing an MCP server."""

    name: str
    description: str = ""
    input_schema: dict[str, object] | None = None
    output_schema: dict[str, object] | None = None
    annotations: dict[str, object] | None = None
    truncated: bool = False


class ServiceMcpTestDiagnostic(BaseModel):
    """One sanitized step in an MCP connection diagnostic."""

    stage: Literal[
        "configuration",
        "dns",
        "tcp",
        "tls",
        "process",
        "authentication",
        "protocol",
        "discovery",
    ]
    status: Literal["success", "error", "warning", "skipped", "info"]
    message: str
    duration_ms: Optional[int] = None


class ServiceMcpTestResponse(BaseModel):
    """Result of an MCP server connection test."""

    success: bool
    message: str
    tested_at: datetime | None = None
    duration_ms: int = 0
    truncated: bool = False
    failure_kind: Optional[
        Literal[
            "configuration",
            "dns",
            "tcp",
            "tls",
            "process",
            "authentication",
            "authorization",
            "endpoint",
            "protocol",
            "timeout",
            "server",
            "unknown",
        ]
    ] = None
    diagnostics: List[ServiceMcpTestDiagnostic] = Field(
        default_factory=list[ServiceMcpTestDiagnostic]
    )
    tools: List[ServiceMcpTestFunction] = Field(
        default_factory=list[ServiceMcpTestFunction]
    )


# =============================================================================
# Internal compatibility model.
# =============================================================================

ConversationToolSource = Literal["native", "external"]


class ConversationToolEntry(BaseModel):
    name: str
    source: ConversationToolSource
    enabled: bool


class ConversationToolCatalog(BaseModel):
    tools: list[ConversationToolEntry]
    discovery_incomplete: bool = False
    next_connection_id: int | None = None


class Service(BaseModel):
    """Internal tool object built from API or database records."""
    code: str
    can_disable: bool = True
    label: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    mcp: Optional[McpConfig] = Field(default=None, alias="mcp_config")
    rest: RestConfig | None = Field(default=None, alias="rest_config")
    file_share: Optional[FileShareConfig] = Field(default=None, alias="file_share_config")
    messenger: Optional[MessengerConfig] = Field(default=None, alias="messenger_config")
    listener: Optional[ListenerConfig] = Field(default=None, alias="listener_config")
    mail: ProtocolConfig | None = Field(default=None, alias="mail_config")
    calendar: ProtocolConfig | None = Field(default=None, alias="calendar_config")
    connection: ConnectionSchema = Field(default_factory=ConnectionSchema, alias="connection_schema")
    task: Optional[TaskConfig] = Field(default=None, alias="task_config")
    conversation_tools: dict[str, list[str]] = Field(default_factory=dict)

    @computed_field
    @property
    def has_api(self) -> bool:
        return self.rest is not None

    @computed_field
    @property
    def has_mcp(self) -> bool:
        return self.mcp is not None

    @computed_field
    @property
    def has_file_share(self) -> bool:
        return self.file_share is not None

    @computed_field
    @property
    def has_messenger(self) -> bool:
        return self.messenger is not None

    @computed_field
    @property
    def has_listener(self) -> bool:
        return self.listener is not None

    @computed_field
    @property
    def has_mail(self) -> bool:
        return self.mail is not None

    @computed_field
    @property
    def has_calendar(self) -> bool:
        return self.calendar is not None

    model_config = {"populate_by_name": True, "from_attributes": True}
