"""Generic HTTP facade for supervised agent harnesses."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status as http_status

from app.agent import Agent, AgentOwnerAssertion, get_agent_record
from core.authorize import Privileges, authorize

from . import facade
from .contracts import HarnessAction
from .schemas import HarnessActionResult, HarnessLogs, HarnessRuntimeState


router = APIRouter(tags=["harnesses"])
supervision_router = APIRouter(prefix="/harnesses/agents")


async def _supervised_agent_or_404(agent_id: int) -> Agent:
    agent = await get_agent_record(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        )
    try:
        facade.supervisor_for(agent)
    except facade.HarnessSupervisorNotFoundError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="This agent driver does not expose managed harness supervision.",
        ) from exc
    return agent


def _service_unavailable(exc: RuntimeError) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
    )


@supervision_router.get("/{id}/status", response_model=HarnessRuntimeState)
@authorize(
    privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT],
    assertion=AgentOwnerAssertion,
)
async def harness_status(id: int) -> HarnessRuntimeState:
    agent = await _supervised_agent_or_404(id)
    try:
        runtime_status = await facade.status(agent)
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc
    return HarnessRuntimeState(
        status=runtime_status,
        capabilities=sorted(facade.capabilities(agent)),
    )


@supervision_router.post("/{id}/actions/{action}", response_model=HarnessActionResult)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def run_harness_action(id: int, action: HarnessAction) -> HarnessActionResult:
    agent = await _supervised_agent_or_404(id)
    try:
        output = await facade.run_action(agent, action)
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc
    return HarnessActionResult(status=action, output=output)


@supervision_router.get("/{id}/logs", response_model=HarnessLogs)
@authorize(
    privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT],
    assertion=AgentOwnerAssertion,
)
async def harness_logs(id: int, lines: int = 300) -> HarnessLogs:
    agent = await _supervised_agent_or_404(id)
    try:
        return HarnessLogs(lines=await facade.logs(agent, lines))
    except RuntimeError as exc:
        raise _service_unavailable(exc) from exc


@supervision_router.post("/{id}/refresh", status_code=http_status.HTTP_202_ACCEPTED)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def refresh_harness(
    id: int,
    background_tasks: BackgroundTasks,
) -> HarnessActionResult:
    agent = await _supervised_agent_or_404(id)
    background_tasks.add_task(facade.refresh, agent)
    return HarnessActionResult(status="refreshing")


@router.post(
    "/runtime-agents/{id}/sync-skills",
    status_code=http_status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
@authorize(privileges=Privileges.SKILL_ASSIGN, assertion=AgentOwnerAssertion)
async def sync_harness_skills(
    id: int,
    background_tasks: BackgroundTasks,
) -> HarnessActionResult:
    """Reconcile driver-projected skills through the generic harness facade."""

    agent = await _supervised_agent_or_404(id)
    background_tasks.add_task(facade.refresh, agent)
    return HarnessActionResult(status="synchronizing")


# Configurable selection and supervision moved to ``app.harnesses``. Keep only the
# hidden skill-reconciliation compatibility endpoint in this concrete package.
