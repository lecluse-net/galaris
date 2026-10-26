"""Authorize existing resources explicitly attached by a human to a Chat message."""

from app.agent import current_management_scope
from app.file_share import ResourceContext, parse_resource_uri, resource_accessible, resource_privileges
from core.authorize import check_privilege
from core.database import get_db
from core.user import user_service


async def prepare_resource_attachments(uris: list[str], *, agent_id: int) -> list[str]:
    if not uris:
        return []
    if len(uris) > 20:
        raise ValueError("At most 20 internal attachments are allowed")
    user = await user_service.get_current_user()
    result: list[str] = []
    for uri in dict.fromkeys(uris):
        if len(uri) > 2048:
            raise ValueError("Attachment URI is too long")
        reference = parse_resource_uri(uri)
        required = resource_privileges(uri)
        if not required or not await check_privilege(user, list(required), get_db()):
            raise PermissionError("Resource unavailable")
        if reference.scheme not in {"document", "data", "memory", "galaris", "https"}:
            if not (await current_management_scope()).allows(agent_id):
                raise PermissionError("Resource unavailable")
        # Resolve in the receiving agent's context as well as checking the human's
        # functional privileges. Selecting a link never grants source access.
        context = ResourceContext(agent_id=agent_id, runtime="internal")
        if not await resource_accessible(context, uri, "read") and not await resource_accessible(context, uri, "list"):
            raise PermissionError("Resource unavailable")
        result.append(str(reference))
    return result
