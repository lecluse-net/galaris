"""Connections and their entity-attribute-value parameters."""

# Models and schemas are always available.
from .models import Connection, ConnectionParam, ConnectionFunctionState, ToolFunctionState
from .schemas import (
    Connection as ConnectionSchema,
    ConnectionCreate,
    ConnectionUpdate,
    ConnectionParam as ConnectionParamSchema,
    ConnectionParamCreate,
    ConnectionParamUpdate,
    ConnectionParamBulkCreate,
    ConnectionParamsResponse,
    AgentByParamResponse,
    ConnectionFunctionInfo,
    ConnectionFunctionsResponse,
    FunctionState,
    FunctionStateUpdate,
    FunctionStateResolved,
)

__all__ = [
    # Models.
    "Connection",
    "ConnectionParam",
    "ConnectionFunctionState",
    "ToolFunctionState",
    # Schemas.
    "ConnectionSchema",
    "ConnectionCreate",
    "ConnectionUpdate",
    "ConnectionParamSchema",
    "ConnectionParamCreate",
    "ConnectionParamUpdate",
    "ConnectionParamBulkCreate",
    "ConnectionParamsResponse",
    "AgentByParamResponse",
    "ConnectionFunctionInfo",
    "ConnectionFunctionsResponse",
    "FunctionState",
    "FunctionStateUpdate",
    "FunctionStateResolved",
]

# Import the service explicitly where needed to avoid circular dependencies.
