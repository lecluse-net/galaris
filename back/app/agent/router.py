from core.util import require_editorial_client
from fastapi import Depends
from fastapi import APIRouter, HTTPException, status, File, UploadFile, Response, Query
from loguru import logger
from typing import List

from core.authorize import authorize, check_privilege, RequireAllPrivilegesAssertion
from core.database import get_db
from core.authorize import Privileges
from core.i18n import render_prompt, tr
from .assertions import AgentOwnerAssertion
from .management_scope import AgentScopeDeniedError, current_management_scope
from .schemas import (
    Title as TitleSchema, TitleCreate, TitleUpdate,
    Agent as AgentSchema, AgentCreate, AgentUpdate,
    AgentGroup as AgentGroupSchema, AgentGroupCreate, AgentGroupUpdate,
    AgentManagerInfo, ExecutorDriverInfo,
)
from . import title_service, agent_service, agent_group_service
from core.user import user_service
from .selection import AgentSelectionOption, AgentSelectionScope, selection_options

router = APIRouter()
from .team_router import router as team_router
router.include_router(team_router)
crud_router = APIRouter(prefix="/agents", tags=["agents"])


async def _detail(key: str) -> str:
    return await tr(f"agent_api.errors.{key}")


async def _require_global_scope() -> None:
    if not (await current_management_scope()).is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global Agent management is required",
        )


# ==================== TITLES CRUD ====================


@crud_router.get("/selection", response_model=list[AgentSelectionOption])
@authorize()
async def read_agent_selection(scope: AgentSelectionScope = "management") -> list[AgentSelectionOption]:
    """Authenticated display metadata never grants a domain operation."""
    if scope == "teams":
        user = await user_service.get_current_user()
        if user is None or not await check_privilege(user, "TEAM_ACCESS", get_db()):
            raise HTTPException(status_code=403, detail="Team access required")
    return await selection_options(scope)


@crud_router.get("/titles", response_model=List[TitleSchema])
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def read_titles(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
):
    return await title_service.get_all(skip=skip, limit=limit)


@crud_router.get("/titles/{id}", response_model=TitleSchema)
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def read_title(
    id: int,
):
    title = await title_service.get(id)
    if title is None:
        raise HTTPException(status_code=404, detail=await _detail("title_not_found"))
    return title


@crud_router.post("/titles", response_model=TitleSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.AGENT_EDIT)
async def create_title(
    title: TitleCreate,
):
    await _require_global_scope()
    return await title_service.create(title)


@crud_router.put("/titles/{id}", response_model=TitleSchema)
@authorize(privileges=Privileges.AGENT_EDIT)
async def update_title(
    id: int,
    title_update: TitleUpdate,
):
    await _require_global_scope()
    title = await title_service.update(id, title_update)
    if title is None:
        raise HTTPException(status_code=404, detail=await _detail("title_not_found"))
    return title


@crud_router.delete("/titles/{id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.AGENT_EDIT)
async def delete_title(
    id: int,
):
    await _require_global_scope()
    deleted = await title_service.delete(id)
    if not deleted:
        raise HTTPException(status_code=404, detail=await _detail("title_not_found"))
    return None


# ==================== AGENT GROUPS CRUD ====================


@crud_router.get("/groups", response_model=List[AgentGroupSchema])
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def read_groups(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
):
    return await agent_group_service.get_all(skip=skip, limit=limit)


@crud_router.get("/groups/{id}", response_model=AgentGroupSchema)
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def read_group(
    id: int,
):
    group = await agent_group_service.get(id)
    if group is None:
        raise HTTPException(status_code=404, detail=await _detail("group_not_found"))
    return group


@crud_router.post("/groups", response_model=AgentGroupSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges="TEAM_EDIT", assertion=RequireAllPrivilegesAssertion, params={"required_privileges": ["TEAM_ACCESS", "TEAM_EDIT"]})
async def create_group(
    group: AgentGroupCreate,
):
    await _require_global_scope()
    return await agent_group_service.create(group)


@crud_router.put("/groups/{id}", response_model=AgentGroupSchema)
@authorize(privileges="TEAM_EDIT", assertion=RequireAllPrivilegesAssertion, params={"required_privileges": ["TEAM_ACCESS", "TEAM_EDIT"]})
async def update_group(
    id: int,
    group_update: AgentGroupUpdate,
):
    await _require_global_scope()
    group = await agent_group_service.update(id, group_update)
    if group is None:
        raise HTTPException(status_code=404, detail=await _detail("group_not_found"))
    return group


@crud_router.delete("/groups/{id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges="TEAM_EDIT", assertion=RequireAllPrivilegesAssertion, params={"required_privileges": ["TEAM_ACCESS", "TEAM_EDIT"]})
async def delete_group(
    id: int,
):
    await _require_global_scope()
    deleted = await agent_group_service.delete(id)
    if not deleted:
        raise HTTPException(status_code=404, detail=await _detail("group_not_found"))
    return None


# ==================== AGENTS CRUD ====================


@crud_router.get("/drivers", response_model=List[ExecutorDriverInfo])
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def read_executor_drivers() -> List[ExecutorDriverInfo]:
    """List registered executor drivers and their current availability.

    The ``app.agent`` facade is the single source used by this API and the UI selector.
    """
    from app.agent import list_driver_specs, list_driver_statuses

    statuses = {status.code: status for status in list_driver_statuses()}
    return [
        ExecutorDriverInfo(
            name=driver.code,
            label_key=driver.label_key,
            available=statuses[driver.code].available,
            manages_runtime=driver.manages_runtime,
            enabled=statuses[driver.code].enabled,
            configured=statuses[driver.code].configured,
            ready=statuses[driver.code].ready,
            reason=statuses[driver.code].reason,
            supports_streaming=driver.supports_streaming,
            supports_cancellation=driver.supports_cancellation,
            use_planner=driver.pipeline_policy.use_planner,
            use_briefing=driver.pipeline_policy.use_briefing,
            briefing_efforts=sorted(driver.pipeline_policy.briefing_efforts),
            execution_efforts=sorted(driver.pipeline_policy.execution_efforts),
            uses_llm_calls=driver.pipeline_policy.uses_llm_calls,
        )
        for driver in list_driver_specs()
    ]


@crud_router.get("", response_model=List[AgentSchema])
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def read_agents(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    agent_driver: str | None = Query(default=None),
):
    scope = await current_management_scope()
    return await agent_service.get_all(
        skip=skip,
        limit=limit,
        agent_driver=agent_driver,
        agent_ids=scope.agent_ids,
    )


@crud_router.get("/managers", response_model=List[AgentManagerInfo])
@authorize(privileges=Privileges.AGENT_EDIT)
async def read_agent_managers() -> List[AgentManagerInfo]:
    """List active human managers available for agent ownership."""
    scope = await current_management_scope()
    users = (
        await user_service.get_users(skip=0, limit=500)
        if scope.is_global
        else [await user_service.get_current_user()]
    )
    current_user_id = user_service.get_current_user_id()
    return [
        AgentManagerInfo(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_current_user=user.id == current_user_id,
        )
        for user in users
        if user is not None and user.is_active
    ]


@crud_router.get("/{id}", response_model=AgentSchema)
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT])
async def read_agent(
    id: int,
):
    scope = await current_management_scope()
    agent = await agent_service.get(id, agent_ids=scope.agent_ids)
    if agent is None:
        raise HTTPException(status_code=404, detail=await _detail("agent_not_found"))
    return agent


@crud_router.post("", dependencies=[Depends(require_editorial_client)], response_model=AgentSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.AGENT_EDIT)
async def create_agent(
    agent: AgentCreate,
):
    try:
        scope = await current_management_scope()
        if (
            agent.user_id is not None
            and agent.user_id != scope.user_id
            and not scope.is_global
        ):
            raise AgentScopeDeniedError(
                "Only a global Agent manager can assign another human manager."
            )
        created = await agent_service.create(agent)
    except AgentScopeDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        logger.warning("Agent creation rejected for '{}': {}", agent.code, e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Unexpected error while creating agent '{}'", agent.code)
        raise

    return created


@crud_router.put("/{id}", dependencies=[Depends(require_editorial_client)], response_model=AgentSchema)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def update_agent(
    id: int,
    agent_update: AgentUpdate,
):
    try:
        scope = await current_management_scope()
        if (
            "user_id" in agent_update.model_fields_set
            and agent_update.user_id != scope.user_id
            and not scope.is_global
        ):
            raise AgentScopeDeniedError(
                "Only a global Agent manager can assign another human manager."
            )
        agent = await agent_service.update(id, agent_update)
        if agent is None:
            raise HTTPException(status_code=404, detail=await _detail("agent_not_found"))
    except AgentScopeDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return agent


@crud_router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def delete_agent(
    id: int,
):
    deleted = await agent_service.delete(id)
    if not deleted:
        raise HTTPException(status_code=404, detail=await _detail("agent_not_found"))
    return None


# ==================== AVATAR ENDPOINTS ====================


@crud_router.post("/{id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def upload_avatar(
    id: int,
    file: UploadFile = File(...),
):
    """Upload an avatar image for an agent."""
    # Validate file type
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=render_prompt(
                await _detail("invalid_avatar_type"),
                types=", ".join(sorted(allowed_types)),
            ),
        )

    # Read file content
    content = await file.read()

    # Validate file size (max 15MB)
    max_size = 15 * 1024 * 1024  # 15MB
    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=await _detail("avatar_too_large"),
        )

    success = await agent_service.update_avatar(id, content)
    if not success:
        raise HTTPException(status_code=404, detail=await _detail("agent_not_found"))
    return None


@crud_router.get("/{id}/avatar")
@authorize(privileges=[Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT, "TEAM_ACCESS"])
async def download_avatar(
    id: int,
):
    """Download the avatar image for an agent."""
    user = await user_service.get_current_user()
    catalogue_access = user is not None and (
        await check_privilege(user, "TEAM_ACCESS", get_db())
    )
    if not catalogue_access and not (await current_management_scope()).allows(id):
        raise HTTPException(status_code=404, detail=await _detail("agent_not_found"))
    avatar_data = await agent_service.get_avatar(id)
    if avatar_data is None:
        raise HTTPException(status_code=404, detail=await _detail("avatar_not_found"))

    # Determine content type from magic bytes
    content_type = "image/jpeg"  # default
    if avatar_data.startswith(b"\x89PNG"):
        content_type = "image/png"
    elif avatar_data.startswith(b"GIF87a") or avatar_data.startswith(b"GIF89a"):
        content_type = "image/gif"
    elif avatar_data.startswith(b"RIFF") and avatar_data[8:12] == b"WEBP":
        content_type = "image/webp"

    return Response(
        content=avatar_data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=86400",
        }
    )


@crud_router.delete("/{id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.AGENT_EDIT, assertion=AgentOwnerAssertion)
async def delete_avatar(
    id: int,
):
    """Delete the avatar for an agent."""
    success = await agent_service.delete_avatar(id)
    if not success:
        raise HTTPException(status_code=404, detail=await _detail("agent_not_found"))
    return None


from .openai_router import router as openai_like_router

router.include_router(crud_router)
router.include_router(openai_like_router)
