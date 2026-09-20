"""Dream inspection is reserved to global Agent managers, including live events."""

from app.agent import management_scope_for
from core import websocket
from core.authorize import Privileges
from core.database import get_db
from core.user import UserModel


class DreamRoom(websocket.BaseRoom):
    """Live monitoring audience, declared by the page while mounted."""


MONITORING_ROOM = DreamRoom("monitoring")


async def _authorize_monitoring(user_id: int, resource_id: str) -> bool:
    if resource_id != "monitoring":
        return False
    user = await get_db().get(UserModel, user_id)
    return user is not None and (await management_scope_for(user, get_db())).is_global


def register_events() -> None:
    websocket.register_resource_room(
        "dream", DreamRoom,
        required_privileges=(Privileges.TASK_ACCESS, Privileges.TASK_EDIT),
        authorize=_authorize_monitoring,
        displayed_only=True,
    )
