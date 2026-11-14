"""Bounded metadata-only verification of a file provider's saved account."""

from app.connection.facade import get_connection, get_params_as_dict
from app.tools.facade import get_tool_by_id

from .file_share_service import build_client
from .file_contracts import FileResourceTransport
from .resource_contracts import ResourceListingTransport


async def test_saved_connection(connection_id: int) -> bool | None:
    connection = await get_connection(connection_id)
    tool = await get_tool_by_id(connection.tool_id) if connection else None
    if tool is None or tool.file_share is None:
        raise ValueError("File provider not found")
    _, params = await get_params_as_dict(connection_id, decrypt_passwords=True)
    transport = build_client(tool.file_share, params)
    if isinstance(transport, ResourceListingTransport):
        await transport.resource_list("/", recursive=False, limit=1)
        return True
    if not isinstance(transport, FileResourceTransport):
        return None
    root = await transport.normalize_resource_path("/", allow_root=True)
    await transport.file_list(root, recursive=False, limit=1)
    return True
