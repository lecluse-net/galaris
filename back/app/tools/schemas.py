"""Pydantic schemas for MCP tools."""

from datetime import datetime
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, computed_field


# =============================================================================
# MCP configuration
# =============================================================================

class McpAuth(BaseModel):
    """Authentication configuration for an MCP server."""
    type: Literal["bearer", "header", "basic", "none"] = "none"

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


class McpAuthPublic(BaseModel):
    """Read model exposing credential presence but never its value."""

    type: Literal["bearer", "header", "basic", "none"] = "none"
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

    # Server-level values shared by every agent connection to this Tool.
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

class ConnectionParamDef(BaseModel):
    """Connection parameter definition."""
    type: str = "string"  # "string", "integer", "password", "boolean"
    required: bool = True
    default: str = ""
    description: str = ""
    order: int | None = None


class ConnectionSchema(BaseModel):
    """Connection parameters keyed by name."""
    params: Dict[str, ConnectionParamDef] = Field(default_factory=lambda: {})


class ToolGlobalParamPublic(BaseModel):
    """Safe global parameter projection; secret literals are write-only."""

    value: Optional[str] = None
    configured: bool = False
    secret: bool = False
    forced: bool = False


class ToolGlobalParamUpdate(BaseModel):
    """One global parameter write.

    ``clear`` is explicit so an omitted password can preserve the existing encrypted value.
    """

    value: Optional[str] = None
    forced: bool = False
    clear: bool = False


class ToolGlobalParamsUpdate(BaseModel):
    params: Dict[str, ToolGlobalParamUpdate] = Field(default_factory=dict)


class ToolGlobalParamsResponse(BaseModel):
    tool_id: int
    params: Dict[str, ToolGlobalParamPublic] = Field(default_factory=dict)


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

class ToolBase(BaseModel):
    code: str
    label: str
    description: str = ""
    mcp_config: Optional[McpConfig] = None
    file_share_config: Optional[FileShareConfig] = None
    messenger_config: Optional[MessengerConfig] = None
    listener_config: Optional[ListenerConfig] = None
    connection_schema: ConnectionSchema = Field(default_factory=ConnectionSchema)
    task_config: Optional[TaskConfig] = None
    conversation_enabled: bool = False


class ToolCreate(ToolBase):
    pass


class ToolUpdate(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    mcp_config: Optional[McpConfig] = None
    file_share_config: Optional[FileShareConfig] = None
    messenger_config: Optional[MessengerConfig] = None
    listener_config: Optional[ListenerConfig] = None
    connection_schema: Optional[ConnectionSchema] = None
    task_config: Optional[TaskConfig] = None
    conversation_enabled: Optional[bool] = None


class ToolRead(ToolBase):
    id: int
    can_disable: bool = True
    created_at: datetime
    updated_at: datetime

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
    def can_edit(self) -> bool:
        from .assertions import tool_can_edit

        return tool_can_edit(self.code)

    model_config = {"from_attributes": True}


class ToolPublic(BaseModel):
    """Public API representation without static tokens."""
    id: int
    code: str
    label: str
    description: str = ""
    has_mcp: bool
    has_file_share: bool
    has_messenger: bool
    has_listener: bool
    can_edit: bool
    can_disable: bool = True
    conversation_enabled: bool = False
    mcp_config: Optional[McpConfigPublic] = None
    file_share_config: Optional[FileShareConfig] = None
    messenger_config: Optional[MessengerConfig] = None
    listener_config: Optional[ListenerConfigPublic] = None
    connection_schema: ConnectionSchema
    global_params: Dict[str, ToolGlobalParamPublic] = Field(default_factory=dict)
    task_config: Optional[TaskConfig] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class McpToolFunctionPublic(BaseModel):
    """MCP function exposed by an application tool."""

    name: str
    description: str = ""
    enabled: bool = False


class ToolMcpCatalogPublic(BaseModel):
    """Application tool MCP catalog for an agent."""

    tool_id: int
    tool_code: str
    tool_label: str
    tool_description: str = ""
    connection_id: Optional[int] = None
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

class ToolMcpTestRequest(BaseModel):
    """Preview an MCP configuration without persisting the Tool."""

    tool_id: Optional[int] = None
    code: str
    mcp_config: McpConfig
    params: Dict[str, Optional[str]] = Field(default_factory=dict)


class ToolMcpTestFunction(BaseModel):
    """Function discovered while testing an MCP server."""

    name: str
    description: str = ""


class ToolMcpTestDiagnostic(BaseModel):
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


class ToolMcpTestResponse(BaseModel):
    """Result of an MCP server connection test."""

    success: bool
    message: str
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
    diagnostics: List[ToolMcpTestDiagnostic] = Field(
        default_factory=list[ToolMcpTestDiagnostic]
    )
    tools: List[ToolMcpTestFunction] = Field(
        default_factory=list[ToolMcpTestFunction]
    )


# =============================================================================
# Internal compatibility model.
# =============================================================================

class Tool(BaseModel):
    """Internal tool object built from API or database records."""
    code: str
    can_disable: bool = True
    label: str
    description: str = ""
    mcp: Optional[McpConfig] = Field(default=None, alias="mcp_config")
    file_share: Optional[FileShareConfig] = Field(default=None, alias="file_share_config")
    messenger: Optional[MessengerConfig] = Field(default=None, alias="messenger_config")
    listener: Optional[ListenerConfig] = Field(default=None, alias="listener_config")
    connection: ConnectionSchema = Field(default_factory=ConnectionSchema, alias="connection_schema")
    task: Optional[TaskConfig] = Field(default=None, alias="task_config")
    conversation_enabled: bool = False

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

    model_config = {"populate_by_name": True, "from_attributes": True}
