from pydantic import BaseModel, ConfigDict
from typing import Optional, Any, Dict, List, Literal


# Three-state function value at connection or tool level. ``default`` means inheritance.
FunctionState = Literal["default", "enabled", "disabled"]


# =============================================================================
# Connection schemas.
# =============================================================================

class ConnectionBase(BaseModel):
    tool_id: int
    agent_id: int
    active: bool = True


class ConnectionCreate(ConnectionBase):
    pass


class ConnectionUpdate(BaseModel):
    tool_id: Optional[int] = None
    agent_id: Optional[int] = None
    active: Optional[bool] = None


class Connection(ConnectionBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# EAV parameter schemas.
# =============================================================================

class ConnectionParamBase(BaseModel):
    connection_id: int
    param_name: str
    param_value: Optional[str] = None


class ConnectionParamCreate(ConnectionParamBase):
    pass


class ConnectionParamUpdate(BaseModel):
    param_value: Optional[str] = None


class ConnectionParam(ConnectionParamBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class ConnectionParamBulkCreate(BaseModel):
    connection_id: int
    params: Dict[str, Optional[str]]


class ConnectionParamsResponse(BaseModel):
    connection_id: int
    tool_id: int
    agent_id: int
    params: Dict[str, Any]
    configured_params: List[str] = []

    model_config = ConfigDict(from_attributes=True)


class AgentByParamQuery(BaseModel):
    tool_id: int
    param_name: str
    param_value: str


class AgentByParamResponse(BaseModel):
    agent_ids: List[int]
    count: int


class RefreshToolCatalogsResponse(BaseModel):
    """Result of the unified connection and MCP catalog refresh."""

    created: int
    agents_scanned: int
    agents_refreshed: int
    agent_failures: int
    source_failures: int
    tools_discovered: int
    documents_indexed: int
    embeddings_refreshed: int
    documents_pruned: int
    semantic_available: bool
    degradation_reason: str | None = None
    complete: bool


class SyncIntegratedConnectionsResponse(RefreshToolCatalogsResponse):
    """Deprecated compatibility response for the former sync endpoint."""


# =============================================================================
# MCP test schemas.
# =============================================================================

class McpToolInfo(BaseModel):
    name: str
    description: str


class TestMcpToolsRequest(BaseModel):
    tool_id: int
    params: Dict[str, Optional[str]] = {}


class TestMcpToolsResponse(BaseModel):
    success: bool
    message: str
    tools: List[McpToolInfo] = []

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# MCP function authorization schemas.
# =============================================================================

class ConnectionFunctionInfo(BaseModel):
    name: str
    description: str
    # Connection and tool cascade states plus the resolved value.
    connection_state: FunctionState
    global_state: FunctionState
    effective: bool


class ConnectionFunctionsResponse(BaseModel):
    success: bool
    message: str
    functions: List[ConnectionFunctionInfo] = []

    model_config = ConfigDict(from_attributes=True)


class FunctionStateUpdate(BaseModel):
    """New state for one level of the function-authorization cascade."""
    state: FunctionState


class FunctionStateResolved(BaseModel):
    """Resolved function state after an update without querying MCP again."""
    name: str
    connection_state: FunctionState
    global_state: FunctionState
    effective: bool
