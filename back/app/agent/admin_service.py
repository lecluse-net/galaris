"""AgentAdmin workflows owned by the Agent domain."""

from typing import Any, Literal

from core.database import get_db
from core.team import list_teams, notify_team_access_changed
from core.user import list_user_records
from app.llm import llm_service, profile_service
from .harness_port import harness_selection_port

from . import agent_service
from .admin_authorization import AdminDelegation
from .dialogue_service import set_agent_membership
from .schemas import Agent as AgentRead


def page(items: list[Any], skip: int, limit: int) -> dict[str, Any]:
    return {"items": items[skip:skip + limit], "total": len(items), "skip": skip, "limit": limit}


async def projection(agent_id: int) -> dict[str, Any]:
    agent = await agent_service.get(agent_id)
    if agent is None:
        raise LookupError("Agent not found")
    return AgentRead.model_validate(agent).model_dump(mode="json")


async def options(
    delegation: AdminDelegation, category: Literal["managers", "profiles", "voices", "harnesses"],
    skip: int, limit: int,
) -> dict[str, Any]:
    if category == "managers":
        if delegation.scope.is_global:
            users = await list_user_records(skip=skip, limit=limit, active_only=True)
            return {"items": [{"id": u.id, "label": u.display_name or u.email} for u in users],
                    "skip": skip, "limit": limit}
        values = [{"id": delegation.manager.id, "label": delegation.manager.display_name or delegation.manager.email}]
    elif category == "profiles":
        values = [{"id": p.id, "label": p.label} for p in await profile_service.list_profiles()]
    elif category == "voices":
        values = [{"value": f"tts:{m.id}", "label": m.label}
                  for m in await llm_service.list_llms(capability="speech") if m.provider.is_active]
        from app.llm import personal_service
        from .voice import VoiceSelection
        selection = await personal_service.selection_options()
        values.extend({"value": VoiceSelection("realtime", v.model_id, v.voice_code).serialize(),
                       "label": v.label} for v in selection.native_voices)
    else:
        values = await harness_selection_port.admin_options()
    return page(values, skip, limit)


async def teams(agent_id: int, skip: int, limit: int) -> dict[str, Any]:
    agent = await agent_service.get(agent_id)
    if agent is None:
        raise LookupError("Agent not found")
    return page([{"id": t.id, "name": t.name, "order": t.order,
                  "present": t.id in agent.team_ids} for t in await list_teams()], skip, limit)


async def team_set(agent_id: int, team_id: int, present: bool) -> dict[str, Any]:
    await set_agent_membership(team_id, agent_id, present)
    await get_db().commit()
    await notify_team_access_changed()
    return await projection(agent_id)
