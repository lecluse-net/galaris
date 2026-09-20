"""
API router for onboarding.

The overview endpoint reports module configuration state so the home page can
decide which setup guidance to display.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.authorize import authorize, Privileges
from core.authorize.logic import check_privilege
from core.user.user_service import get_current_user
from core.user.models import User
from core.database import get_db
from app.agent import management_scope_for

from .schemas import OnboardingStatusResponse, OnboardingOverviewResponse
from . import services

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/overview", response_model=OnboardingOverviewResponse)
@authorize()  # Any authenticated user may access this route.
async def get_onboarding_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Return the onboarding state of every supported module.

    For each module:
    - show is true when the user has access and no data exists yet.
    - has_privilege states whether the user has the required privilege.
    - has_data states whether the module already contains data.

    Returns:
        The complete module onboarding overview.
    """
    # Resolve privileges through the standard authorization service.
    has_llm_privilege = await check_privilege(current_user, Privileges.LLM_PROVIDER_EDIT, db)
    has_tools_privilege = await check_privilege(current_user, Privileges.TOOL_ACCESS, db)
    has_connections_privilege = await check_privilege(current_user, Privileges.CONNECTION_EDIT, db)
    has_agents_privilege = await check_privilege(current_user, Privileges.AGENT_EDIT, db)
    has_skills_access = await check_privilege(
        current_user,
        [Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN],
        db,
    )
    has_processes_access = await check_privilege(
        current_user,
        [Privileges.PROCESS_READ, Privileges.PROCESS_LAUNCH, Privileges.PROCESS_ADMIN],
        db,
    )
    scope = await management_scope_for(current_user, db)

    # Configuration state drives onboarding independently from edit rights.
    # Privileges only control whether the user may act on an incomplete step.
    has_llm_data = await services.check_llm_status()
    has_tools_data = await services.check_tools_status()
    has_connections_data = await services.check_messaging_status(
        agent_ids=scope.agent_ids
    )
    has_agents_data = await services.check_agent_status(agent_ids=scope.agent_ids)
    has_skills_data = await services.check_skills_status()
    has_processes_data = await services.check_processes_status(
        agent_ids=scope.agent_ids
    )

    return OnboardingOverviewResponse(
        llm_provider=OnboardingStatusResponse(
            show=has_llm_privilege and not has_llm_data,
            has_privilege=has_llm_privilege,
            has_data=has_llm_data
        ),
        tools=OnboardingStatusResponse(
            show=has_tools_privilege and not has_tools_data,
            has_privilege=has_tools_privilege,
            has_data=has_tools_data
        ),
        connections=OnboardingStatusResponse(
            show=has_connections_privilege and not has_connections_data,
            has_privilege=has_connections_privilege,
            has_data=has_connections_data
        ),
        agents=OnboardingStatusResponse(
            show=has_agents_privilege and not has_agents_data,
            has_privilege=has_agents_privilege,
            has_data=has_agents_data
        ),
        skills=OnboardingStatusResponse(
            show=has_skills_access and not has_skills_data,
            has_privilege=has_skills_access,
            has_data=has_skills_data,
        ),
        processes=OnboardingStatusResponse(
            show=has_processes_access and not has_processes_data,
            has_privilege=has_processes_access,
            has_data=has_processes_data,
        ),
        skills_access=has_skills_access,
        processes_access=has_processes_access,
    )
