"""Provider credential checks without sending messages or starting listeners."""

from app.connection.facade import get_connection
from app.tools.facade import get_tool_by_id

from .facade import get_factory, is_kind_enabled
from .interface import Messenger


async def test_saved_connection(connection_id: int) -> bool | None:
    connection = await get_connection(connection_id)
    tool = await get_tool_by_id(connection.tool_id) if connection is not None else None
    if tool is None or tool.messenger is None:
        raise ValueError("Messaging connection not found")
    service = tool.messenger.service
    factory = get_factory(service)
    if not is_kind_enabled(service) or factory is None:
        raise ValueError("Messaging bridge unavailable")
    if factory.check_connection is Messenger.check_connection:
        return None
    messenger = await factory.from_connection_id(connection_id)
    try:
        await messenger.check_connection()
        return True
    finally:
        await messenger.close()
