"""Administration endpoints for canonical messaging configuration and user search."""

from fastapi import APIRouter, Query
from core.authorize import Privileges, authorize
from app.agent import AgentOwnerAssertion

from . import facade
from .schemas import (
    MessengerBridgeInfo,
    MessengerConfigurationCheck,
    MessengerUserSearchResult,
)
from .service import check_configuration, search_agent_users

router = APIRouter(prefix="/messenger", tags=["messenger"])


@router.get("/bridges", response_model=list[MessengerBridgeInfo])
@authorize(privileges=[Privileges.TOOL_ACCESS, Privileges.TOOL_EDIT])
async def list_messenger_bridges() -> list[MessengerBridgeInfo]:
    """List services and parameters available to a Tool's Messenger capability."""

    return [
        MessengerBridgeInfo.model_validate(item)
        for item in facade.available_bridges()
    ]


@router.post("/configuration/test", response_model=MessengerConfigurationCheck)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def test_messenger_configuration() -> MessengerConfigurationCheck:
    """Validate active credentials and report inbound-listener health."""
    return MessengerConfigurationCheck.model_validate(await check_configuration())


@router.get("/users", response_model=list[MessengerUserSearchResult])
@authorize(
    privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT],
    assertion=AgentOwnerAssertion,
)
async def search_messenger_users(
    agent_id: int = Query(gt=0),
    query: str = Query(default="", max_length=500),
) -> list[MessengerUserSearchResult]:
    """Return all matching identities from every enabled messaging connection."""

    results: list[MessengerUserSearchResult] = []
    for connection_id, tool_id, platform, user in await search_agent_users(
        agent_id, query
    ):
        results.append(
            MessengerUserSearchResult(
                id=user.id,
                messaging_id=connection_id,
                tool_id=tool_id,
                platform=platform,
                external_id=user.external_id,
                user_id=str(user.id),
                display_name=user.display_name or user.external_id,
                agent_id=user.agent_id,
            )
        )
    return results


@router.get("/channels", response_model=list[str])
@authorize(privileges=[Privileges.CONNECTION_ACCESS, Privileges.CONNECTION_EDIT])
async def list_enabled_messenger_channels() -> list[str]:
    """Return only the messaging channels currently visible outside preferences."""

    return facade.enabled_kinds()
