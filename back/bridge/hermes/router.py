"""Hermes management and runtime-integration routes.

Per-agent MCP is served by the unified authenticated Streamable HTTP endpoint in
``app.mcp.router``. The packaged Hermes MemoryProvider uses the independently
authenticated endpoints owned here.
"""

from fastapi import APIRouter, HTTPException, Request, status
from core.authorize import Privileges, authorize, independent_auth
from core.i18n import tr

from app.agent import (
    Agent,
    AgentOwnerAssertion,
    current_management_scope,
    get_agent_record,
    list_agent_records,
)
from app.memory import (
    MemoryAcquisitionCreate,
    MemoryAcquisitionResult,
    acquire_memory,
)

from . import approvals as _approvals  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .manager import manager
from .memory_provider import get_memory_context
from . import config_service
from .schemas import (
    HermesAgentConfiguration,
    HermesConfigUpdate,
    HermesMemoryRememberRequest,
    HermesMemorySearchRequest,
    HermesMemorySearchResult,
)

router = APIRouter(tags=["Hermes Management"])


async def _agent_or_404(agent_id: int) -> Agent:
    agent = await get_agent_record(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await tr("hermes.errors.agent_not_found"),
        )
    return agent


async def _hermes_agent_or_400(agent_id: int) -> Agent:
    agent = await _agent_or_404(agent_id)
    if agent.agent_driver != "hermes":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=await tr("hermes.errors.wrong_driver"),
        )
    await config_service.hydrate_agent(agent)
    return agent


@router.get(
    "/hermes/configurations",
    response_model=list[HermesAgentConfiguration],
    summary="List Hermes agent configurations",
)
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def list_hermes_configurations() -> list[HermesAgentConfiguration]:
    scope = await current_management_scope()
    agents = await list_agent_records(
        driver_code="hermes",
        agent_ids=scope.agent_ids,
    )
    return [
        await config_service.public_configuration(agent)
        for agent in agents
    ]


@router.put(
    "/hermes/configurations/{id}",
    response_model=HermesAgentConfiguration,
    summary="Update one Hermes agent configuration",
)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def update_hermes_configuration(
    id: int,
    data: HermesConfigUpdate,
) -> HermesAgentConfiguration:
    agent = await _hermes_agent_or_400(id)
    try:
        return await config_service.update_configuration(agent, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/hermes/reachable",
    summary="Check Hermes bridge connectivity",
)
@authorize(privileges=[Privileges.HERMES_ACCESS, Privileges.HERMES_EDIT])
async def hermes_reachable() -> dict[str, bool]:
    """Return whether the selected Hermes management backend is reachable."""

    return {"reachable": await manager.check_reachable()}


@router.get(
    "/hermes/agents",
    summary="List Hermes runtime instances",
)
@authorize(privileges=[Privileges.HERMES_ACCESS, Privileges.HERMES_EDIT])
async def hermes_list_agents() -> dict[str, list[str]]:
    """List instances declared by the Hermes management backend."""

    try:
        scope = await current_management_scope()
        managed_codes = {
            agent.code
            for agent in await list_agent_records(
                driver_code="hermes",
                agent_ids=scope.agent_ids,
            )
        }
        return {
            "agents": [
                code for code in await manager.list_agents() if code in managed_codes
            ]
        }
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


async def _memory_provider_agent_id(request: Request) -> int:
    """Authenticate a Hermes MemoryProvider call with its rotated MCP token."""

    from app.mcp import mcp_token_service

    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Hermes memory provider token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    matched = await mcp_token_service.get_enabled_system_token_by_value(token)
    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Hermes memory provider token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return matched.agent_id


@router.post(
    "/memory/provider/search",
    response_model=HermesMemorySearchResult,
    include_in_schema=False,
)
@independent_auth(reason="Hermes system MCP bearer token")
async def hermes_provider_search(
    data: HermesMemorySearchRequest, request: Request
) -> HermesMemorySearchResult:
    """Return the exact brief prepared before driver selection, without reranking."""

    agent_id = await _memory_provider_agent_id(request)
    del data
    from app.agent import get_current_task

    task_id = get_current_task(agent_id)
    if task_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hermes memory reads require an active Galaris task scope.",
        )
    prepared = get_memory_context(agent_id=agent_id, task_id=task_id)
    return HermesMemorySearchResult(
        context=prepared.context if prepared is not None else "",
        memories=[],
    )


@router.post("/memory/provider/remember", include_in_schema=False)
@independent_auth(reason="Hermes system MCP bearer token")
async def hermes_provider_remember(
    data: HermesMemoryRememberRequest, request: Request
) -> MemoryAcquisitionResult:
    """Apply an explicit built-in Hermes memory write through memory governance."""

    agent_id = await _memory_provider_agent_id(request)
    from app.agent import get_current_task

    task_id = get_current_task(agent_id)
    if task_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hermes memory writes require an active Galaris task scope.",
        )
    return await acquire_memory(
        MemoryAcquisitionCreate(
            agent_id=agent_id,
            action="create",
            title=data.title,
            content=data.content,
            source_kind="hermes_builtin_memory",
            source_ref=f"task:{task_id}:hermes-memory",
            metadata={
                **data.metadata,
                "memory_type": "core" if data.target == "user" else "semantic",
                "hermes_target": data.target,
                "hermes_action": data.action,
                "hermes_session_id": data.session_id,
                "galaris_task_id": str(task_id),
            },
        )
    )
