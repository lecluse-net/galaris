from collections.abc import Collection
from typing import Any, Sequence, Optional
import re
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from loguru import logger

from core.database import get_db
from core.i18n import render_prompt, tr
from core.user import user_service
from app.llm import llm_service, profile_service

from .models import Title, Agent, AgentGroup, AgentTeam
from .observers import notify_agent_profile
from .schemas import AgentCreate, AgentUpdate
from .voice import parse_voice_selection
from .facade import validate_agent_driver, resolve_driver

_AGENT_CODE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


async def _normalize_code(code: Optional[str]) -> str:
    normalized = (code or "").strip()
    if not normalized:
        raise ValueError(await tr("agent_api.errors.code_required"))
    if len(normalized) > 50:
        raise ValueError(await tr("agent_api.errors.code_too_long"))
    if not _AGENT_CODE_RE.fullmatch(normalized):
        raise ValueError(await tr("agent_api.errors.code_invalid"))
    return normalized


async def _set_transient_flags(agent: Agent) -> None:
    teams = set((await get_db().scalars(select(AgentTeam.team_id).join(AgentGroup, AgentGroup.id == AgentTeam.team_id)
                                      .where(AgentTeam.agent_id == agent.id))).all())
    if agent.group_id is not None and await get_db().scalar(select(AgentGroup.id).where(AgentGroup.id == agent.group_id)) is not None:
        teams.add(agent.group_id)
    agent.team_ids = sorted(teams)
    agent.has_avatar = agent.avatar is not None
    agent.is_owner = agent.user_id == user_service.get_current_user_id()


async def _require_team_members_edit() -> None:
    from core.authorize import check_privilege
    user = await user_service.get_current_user()
    if (user is None
        or not await check_privilege(user, "TEAM_ACCESS", get_db())
        or not await check_privilege(user, "TEAM_MEMBERS_EDIT", get_db())):
        from .management_scope import AgentScopeDeniedError
        raise AgentScopeDeniedError("TEAM_ACCESS and TEAM_MEMBERS_EDIT are required to change team memberships")


async def _ensure_skill_assignment_matrix(agent_id: int) -> None:
    """Materialize the skill settings for every supported agent driver."""
    from app.skill import skill_service

    await skill_service.ensure_assignment_matrix(agent_id=agent_id)


async def _validate_model_selection(
    resource_id: Optional[int],
    capability: str,
    field: str,
    *,
    resource_type: str | None = None,
) -> None:
    """Reject missing or capability-incompatible configured AI resources."""
    if resource_id is None:
        return
    resource = await llm_service.get_llm(resource_id)
    if resource is None:
        raise ValueError(f"{field}: ressource IA introuvable ({resource_id})")
    if capability not in resource.service_capabilities:
        raise ValueError(
            f"{field}: la ressource {resource.label!r} ne prend pas en charge {capability}"
        )
    if resource_type is not None and resource.resource_type != resource_type:
        raise ValueError(
            f"{field}: la ressource {resource.label!r} doit être de type {resource_type}"
        )


async def _validate_voice_selection(value: str | None) -> None:
    """Validate the one per-agent Voice/TTS selection against the catalog."""
    selection = parse_voice_selection(value)
    if selection is None:
        return
    capability = "speech" if selection.mode == "tts" else "realtime_conversation"
    await _validate_model_selection(selection.model_id, capability, "voice")


def _agent_load_options() -> tuple[Any, ...]:
    return (
        selectinload(Agent.title),
        selectinload(Agent.profile),
        selectinload(Agent.user),
    )


async def _validate_manager(user_id: int | None) -> int:
    """Resolve and validate the mandatory human manager of an agent."""
    resolved_user_id = user_id
    if resolved_user_id is None:
        resolved_user_id = user_service.get_current_user_id()
    if resolved_user_id is None:
        raise ValueError(await tr("agent_api.errors.manager_required"))
    manager = await user_service.get_user_by_id(resolved_user_id)
    if manager is None or not manager.is_active:
        raise ValueError(await tr("agent_api.errors.invalid_manager"))
    return resolved_user_id


async def get_all(
    skip: int = 0,
    limit: int = 50,
    agent_driver: str | None = None,
    agent_ids: Collection[int] | None = None,
) -> Sequence[Agent]:
    """Get all agents with pagination."""
    logger.info("Listing agents")
    db = get_db()
    query = select(Agent).options(*_agent_load_options())
    if agent_driver is not None:
        query = query.where(Agent.agent_driver == agent_driver)
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    query = query.order_by(Agent.code, Agent.id).offset(skip).limit(limit)
    query = Agent.histo_filter(query)
    result = await db.execute(query)
    agents = result.scalars().all()
    for agent in agents:
        await _set_transient_flags(agent)
    return agents


async def get(
    id: int,
    *,
    agent_ids: Collection[int] | None = None,
) -> Optional[Agent]:
    """Get an agent by ID."""
    db = get_db()
    query = select(Agent).options(*_agent_load_options()).where(Agent.id == id)
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    query = Agent.histo_filter(query)
    result = await db.execute(query)
    agent = result.scalar_one_or_none()
    if agent:
        await _set_transient_flags(agent)
    return agent


async def create(agent_data: AgentCreate) -> Agent:
    """Create a new agent."""
    db = get_db()
    code = await _normalize_code(agent_data.code)
    manager_user_id = await _validate_manager(agent_data.user_id)
    validate_agent_driver(agent_data.agent_driver)
    if agent_data.agent_driver != resolve_driver(None).code:
        raise ValueError(
            "Create the agent with its internal Harness, then install another Harness "
            "through /harnesses/agents/{id}."
        )
    # Verify title exists
    title_result = await db.execute(select(Title).where(Title.id == agent_data.title_id))
    if title_result.scalar_one_or_none() is None:
        raise ValueError(await tr("agent_api.errors.invalid_title"))

    # Verify group exists if provided
    if agent_data.group_id is not None:
        await _require_team_members_edit()
        group_result = await db.execute(select(AgentGroup).where(AgentGroup.id == agent_data.group_id))
        if group_result.scalar_one_or_none() is None:
            raise ValueError(await tr("agent_api.errors.invalid_group"))

    # ``None`` is meaningful: this agent follows the current profile.
    if (
        agent_data.profile_id is not None
        and await profile_service.get_profile(agent_data.profile_id) is None
    ):
        raise ValueError(
            render_prompt(
                await tr("llm_api.errors.profile_not_found"),
                profile_id=agent_data.profile_id,
            )
        )
    await _validate_voice_selection(agent_data.voice)

    # Create the agent
    data = agent_data.model_dump()
    data["code"] = code
    data["user_id"] = manager_user_id
    new_agent = Agent(**data)
    db.add(new_agent)
    try:
        await db.flush()
        if new_agent.group_id is not None:
            from .dialogue_service import set_agent_membership
            await set_agent_membership(new_agent.group_id, new_agent.id, True)
        await _ensure_skill_assignment_matrix(new_agent.id)
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise ValueError(await tr("agent_api.errors.create_conflict")) from e
    await db.refresh(new_agent)

    # Eagerly load the title relationship
    result = await db.execute(
        select(Agent)
        .options(*_agent_load_options())
        .where(Agent.id == new_agent.id)
    )
    new_agent = result.scalar_one()

    from app.tools.mandatory_tools import sync_integrated_tool_connections

    await sync_integrated_tool_connections(new_agent.id)
    await db.commit()
    await _set_transient_flags(new_agent)

    logger.info(f"Agent created: {new_agent.first_name} {new_agent.last_name}")
    await notify_agent_profile(new_agent.id, "create")
    return new_agent


async def update(id: int, agent_update: AgentUpdate) -> Optional[Agent]:
    """Update an existing agent."""
    db = get_db()
    result = await db.execute(select(Agent).where(Agent.id == id))
    agent = result.scalar_one_or_none()
    if agent is None:
        return None

    fields_set = agent_update.model_fields_set
    if "group_id" in fields_set and agent_update.group_id != agent.group_id:
        from .dialogue_service import set_agent_membership
        await _require_team_members_edit()
        previous_team = agent.group_id
        if previous_team is not None:
            await set_agent_membership(previous_team, agent.id, False)
        if agent_update.group_id is not None:
            await set_agent_membership(agent_update.group_id, agent.id, True)
    if "code" in fields_set:
        requested_code = await _normalize_code(agent_update.code)
        if requested_code != agent.code:
            raise ValueError(await tr("agent_api.errors.code_immutable"))
    if "agent_driver" in fields_set:
        requested_driver = validate_agent_driver(agent_update.agent_driver)
        if requested_driver != agent.agent_driver:
            raise ValueError(
                "Harness selection cannot be changed through the Agent API; use "
                "/harnesses/agents/{id} so the previous runtime is destroyed first."
            )
        agent_update.agent_driver = requested_driver
    if "user_id" in fields_set:
        agent_update.user_id = await _validate_manager(agent_update.user_id)

    # Verify title exists if provided
    if agent_update.title_id is not None:
        title_result = await db.execute(select(Title).where(Title.id == agent_update.title_id))
        if title_result.scalar_one_or_none() is None:
            raise ValueError(await tr("agent_api.errors.invalid_title"))

    # Verify group exists if provided
    if agent_update.group_id is not None:
        group_result = await db.execute(select(AgentGroup).where(AgentGroup.id == agent_update.group_id))
        if group_result.scalar_one_or_none() is None:
            raise ValueError(await tr("agent_api.errors.invalid_group"))

    # ``None`` switches the agent back to the current profile.
    if "profile_id" in fields_set:
        profile_id = agent_update.profile_id
        if profile_id is not None and await profile_service.get_profile(profile_id) is None:
            raise ValueError(
                render_prompt(
                    await tr("llm_api.errors.profile_not_found"),
                    profile_id=profile_id,
                )
            )
    if "voice" in fields_set:
        await _validate_voice_selection(agent_update.voice)

    update_data = agent_update.model_dump(exclude_unset=True)
    # ``code`` is the agent's permanent system identity. Older clients may still
    # echo its current value, but it must never be written during an update.
    update_data.pop("code", None)
    for key, value in update_data.items():
        setattr(agent, key, value)

    try:
        await _ensure_skill_assignment_matrix(agent.id)
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise ValueError(await tr("agent_api.errors.update_conflict")) from e
    await db.refresh(agent)

    # Eagerly load the title and llm relationships
    result = await db.execute(
        select(Agent).options(*_agent_load_options()).where(Agent.id == id)
    )
    agent = result.scalar_one()

    await _set_transient_flags(agent)

    logger.info(f"Agent updated: {agent.first_name} {agent.last_name}")
    await notify_agent_profile(agent.id, "update")
    return agent


async def delete(id: int) -> bool:
    """Soft delete an agent. Returns True if deleted, False if not found."""
    db = get_db()
    result = await db.execute(select(Agent).where(Agent.id == id))
    agent = result.scalar_one_or_none()
    if agent is None:
        return False

    agent.soft_delete()
    await db.commit()
    logger.info(f"Agent deleted: {id}")
    await notify_agent_profile(id, "delete")
    return True


async def update_avatar(id: int, avatar_data: bytes) -> bool:
    """Update the avatar for an agent. Returns True if updated, False if not found."""
    db = get_db()
    result = await db.execute(select(Agent).where(Agent.id == id))
    agent = result.scalar_one_or_none()
    if agent is None:
        return False

    agent.avatar = avatar_data
    await db.commit()
    logger.info(f"Avatar updated for agent: {id}")
    return True


async def get_avatar(id: int) -> Optional[bytes]:
    """Get the avatar data for an agent. Returns None if not found or no avatar."""
    db = get_db()
    result = await db.execute(select(Agent).where(Agent.id == id))
    agent = result.scalar_one_or_none()
    if agent is None:
        return None
    return agent.avatar


async def delete_avatar(id: int) -> bool:
    """Delete the avatar for an agent. Returns True if deleted, False if not found."""
    db = get_db()
    result = await db.execute(select(Agent).where(Agent.id == id))
    agent = result.scalar_one_or_none()
    if agent is None:
        return False

    agent.avatar = None
    await db.commit()
    logger.info(f"Avatar deleted for agent: {id}")
    return True


async def get_by_code(
    code: str,
    *,
    agent_ids: Collection[int] | None = None,
) -> Optional[Agent]:
    """Get an agent by code."""
    db = get_db()
    query = select(Agent).where(Agent.code == code)
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    query = Agent.histo_filter(query)
    result = await db.execute(query)
    return result.scalar_one_or_none()
