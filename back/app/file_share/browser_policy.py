"""Functional gates for HTTP transport; source/provider ACLs still apply afterwards."""

from core.authorize import Privileges, BaseAssertion, AssertionContext, check_privilege
from core.database import get_db
from fastapi import HTTPException
from app.agent import current_management_scope
from .resource_contracts import ResourceContext
from .resource_uri import parse_resource_uri
from .native_providers import resolve_native_alias


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
