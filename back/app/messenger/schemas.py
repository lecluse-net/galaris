"""Public messenger API schemas and generic agent dispatch aliases."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.agent.contracts import DispatchDecision, DispatchResult


class MessengerConnectionCheck(BaseModel):
    """Read-only configuration and listener check for one agent connection."""

    connection_id: int
    agent_id: int
    provider: str
    ok: bool
    identity: str = ""
    detail: str = ""
    receiving: bool | None = None
    last_received_at: datetime | None = None


class MessengerConfigurationCheck(BaseModel):
    """Aggregate check for every configured messaging provider."""

    provider: str
    ok: bool
    connections: list[MessengerConnectionCheck]


class MessengerUserSearchResult(BaseModel):
    """One exact user identity reachable through one messaging connection."""

    id: UUID
    messaging_id: int
    tool_id: int
    platform: str
    external_id: str
    user_id: str
    display_name: str
    agent_id: int | None = None


class MessengerBridgeParam(BaseModel):
    """One server setting or connection mapping declared by a bridge."""

    key: str
    label: str
    type: str = "string"
    required: bool = True
    default: str = ""
    description: str = ""


class MessengerBridgeInfo(BaseModel):
    """Bridge metadata used to build a Tool's Messenger tab."""

    service: str
    label: str
    settings: list[MessengerBridgeParam] = Field(
        default_factory=list[MessengerBridgeParam]
    )
    params: list[MessengerBridgeParam] = Field(
        default_factory=list[MessengerBridgeParam]
    )


__all__ = [
    "DispatchDecision",
    "DispatchResult",
    "MessengerConfigurationCheck",
    "MessengerConnectionCheck",
    "MessengerUserSearchResult",
    "MessengerBridgeInfo",
    "MessengerBridgeParam",
]
