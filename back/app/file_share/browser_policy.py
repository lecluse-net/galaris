"""Functional gates for HTTP transport; source/provider ACLs still apply afterwards."""

from uuid import UUID

from core.authorize import Privileges, BaseAssertion, AssertionContext, check_privilege
from core.database import get_db
from fastapi import HTTPException
from app.agent import AgentManagementScope, current_management_scope
from core.user import UserModel
from .resource_contracts import ResourceContext
from .resource_uri import parse_resource_uri
from .native_providers import resolve_native_alias


async def review_calendar_event_label(
    calendar_id: int, uid: str, *, reviewer: UserModel, scope: AgentManagementScope,
) -> str | None:
    from .galaris_provider import calendar_event_label

    if not await check_privilege(reviewer, [Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT], get_db()):
        return None
    return await calendar_event_label(calendar_id, uid, scope.agent_ids)


async def review_resource(
    uri: str, *, agent_id: int, reviewer: UserModel, scope: AgentManagementScope,
) -> tuple[str, str | None] | None:
    """Name a local approval target using the reviewer's own read permissions."""
    from app.document.facade import DocumentError, document_actor, get_item_metadata
    from app.goal import goal_service
    from app.messenger import get_chat_room
    from .resource_observation import suspend_observations
    from .resource_service import resource_info

    reference = parse_resource_uri(uri)
    kind = reference.segments[0] if reference.scheme == "galaris" else reference.scheme
    room = kind == "room"
    required = (Privileges.CHAT_ACCESS,) if room else resource_privileges(uri)
    if not await check_privilege(reviewer, list(required), get_db()):
        return None
    try:
        if room:
            detail = await get_chat_room(scope.user_id, UUID(reference.segments[1]))
            return (detail.label, uri) if detail and detail.label else None
        if kind == "goal":
            goal = await goal_service.get_detail(UUID(reference.segments[1]))
            if goal is None or not scope.allows(goal.agent_id):
                return None
            if goal.referrer and goal.referrer.type == "AGENT" and not scope.allows(goal.referrer.agent_id):
                return None
            return goal.title, uri
        if kind == "document":
            identity = UUID(reference.locator)
            item, _ = await get_item_metadata(identity, agent_id=await document_actor(identity, scope))
            if item.document_format == "process":
                return None
            return item.title, f"data://{identity}" if item.document_format == "dataset" else uri
        if not scope.allows(agent_id) or (kind == "agent" and not scope.allows(int(reference.segments[1]))):
            return None
        with suspend_observations():
            descriptor = await resource_info(ResourceContext(agent_id=agent_id, runtime="internal",
                browser_navigation=True, management_scope=scope), reference)
        owner = descriptor.metadata.get("agent_id")
        if isinstance(owner, int) and not scope.allows(owner):
            return None
        label = descriptor.metadata.get("label") or descriptor.name
        if descriptor.is_collection or not isinstance(label, str) or not label.strip():
            return None
        link = descriptor.uri if kind != "file" and not descriptor.uri.startswith("galaris://process/") else None
        return label, link
    except (LookupError, FileNotFoundError, PermissionError, ValueError, DocumentError):
        return None


def resource_privileges(uri: str, *, write: bool = False) -> tuple[str, ...]:
    reference = parse_resource_uri(uri, allow_empty=True)
    read: tuple[str, ...]
    edit: tuple[str, ...]
    if reference.scheme == "mail":
        read, edit = (Privileges.MAIL_ACCESS,), (Privileges.MAIL_EDIT,)
        if write:
            return ()
    elif reference.scheme == "document":
        read, edit = (
            (Privileges.DOCUMENT_ACCESS,),
            (Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN),
        )
        if not reference.locator or reference.segments[:1] == ("folders",):
            read = (*read, Privileges.DATASET_READ, Privileges.DATASET_EDIT, Privileges.DATASET_ADMIN)
    elif reference.scheme == "data":
        read, edit = (Privileges.DATASET_READ,), (Privileges.DATASET_EDIT, Privileges.DATASET_ADMIN)
    elif reference.scheme == "memory":
        read, edit = (Privileges.MEMORY_ACCESS,), (Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN)
    elif reference.scheme == "galaris":
        domains = {
            "contact": (Privileges.CONTACT_ACCESS, Privileges.CONTACT_EDIT),
            "code": (Privileges.CODE_ACCESS,),
            "calendar": (Privileges.CALENDAR_ACCESS, Privileges.CALENDAR_EDIT),
            "topic": (Privileges.TOPIC_ACCESS,),
            "agent": (Privileges.AGENT_ACCESS, Privileges.AGENT_EDIT),
            "process": (Privileges.PROCESS_READ, Privileges.PROCESS_EDIT, Privileges.PROCESS_ADMIN),
            "task": (Privileges.TASK_ACCESS, Privileges.TASK_EDIT),
            "text": (Privileges.CONVERSATION_ACCESS, Privileges.CONVERSATION_CONTROL),
            "voice": (Privileges.VOICE_HISTORY_ACCESS, Privileges.VOICE_HISTORY_CONTROL),
            "goal": (Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT),
            "goal_cycle": (Privileges.GOAL_ACCESS, Privileges.GOAL_EDIT),
            "skill": (Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT),
        }
        if write:
            return ()
        collection = reference.segments[0] if reference.segments else ""
        if collection == "processes":
            collection = "process"
        if not collection:
            return tuple(dict.fromkeys(code for values in domains.values() for code in values))
        return domains.get(collection, ())
    else:
        read, edit = (Privileges.FILE_ACCESS,), (Privileges.FILE_EDIT,)
    return edit if write else (*read, *edit)


BROWSER_PRIVILEGES = tuple(
    dict.fromkeys(
        code
        for uri in ("file://", "document://", "data://", "memory://", "galaris://", "mail://")
        for code in resource_privileges(uri)
    )
)


class BrowserResourceAssertion(BaseAssertion):
    async def assert_route(
        self, route_name: str, params: dict[str, object], context: AssertionContext
    ) -> bool:
        del route_name
        # These endpoints declare URI/agent as Query parameters. A JSON body on
        # GET/PATCH must not authorize another URI than the handler will use.
        if context.request is None:
            return False
        uri = context.request.query_params.get("uri")
        if not isinstance(uri, str) or context.user is None:
            return False
        try:
            reference = parse_resource_uri(uri, allow_empty=True)
            if reference.scheme == "document" and reference.segments:
                # Verified legacy Dataset aliases retain the Dataset's domain.
                # Reject unrelated roles before invoking the legacy adapter.
                eligible = [
                    Privileges.DOCUMENT_ACCESS,
                    Privileges.DOCUMENT_EDIT,
                    Privileges.DOCUMENT_ADMIN,
                    Privileges.DATASET_READ,
                    Privileges.DATASET_EDIT,
                    Privileges.DATASET_ADMIN,
                ]
                if not await check_privilege(context.user, eligible, get_db()):
                    return False
                agent_id = int(context.request.query_params.get("agent_id", ""))
                if not (await current_management_scope()).allows(agent_id):
                    raise HTTPException(404, "Agent not found")
                try:
                    reference = await resolve_native_alias(
                        ResourceContext(agent_id=agent_id, runtime="internal"), reference
                    )
                except (LookupError, PermissionError) as exc:
                    raise HTTPException(404, "Resource unavailable") from exc
            required = resource_privileges(str(reference), write=params.get("mutation") is True)
        except ValueError:
            return False
        return bool(required) and await check_privilege(context.user, list(required), get_db())
