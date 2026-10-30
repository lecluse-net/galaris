"""Authorized reads for explicit file-to-document imports."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from app.agent import AgentManagementScope, get_agent_record
from app.document import DocumentImportSource, read_native_document_import
from core.authorize import check_privilege
from core.database import get_db
from core.params import runtime_settings
from core.user import get_current_user
from .browser import browser_context
from .browser_policy import resource_privileges
from .resource_service import materialize_resource, resource_info
from .native_providers import resolve_native_alias
from .resource_uri import parse_resource_uri


async def read_document_import_source(uri: str, agent_id: int, scope: AgentManagementScope) -> DocumentImportSource:
    user = await get_current_user()
    required = resource_privileges(uri)
    if (not scope.allows(agent_id) or await get_agent_record(agent_id) is None
        or user is None or not required or not await check_privilege(user, list(required), get_db())):
        raise PermissionError("Source resource unavailable")
    async with asyncio.timeout(120), browser_context(agent_id, scope=scope) as ctx:
        reference = await resolve_native_alias(ctx, parse_resource_uri(uri))
        resolved_privileges = resource_privileges(str(reference))
        if not resolved_privileges or not await check_privilege(user, list(resolved_privileges), get_db()):
            raise PermissionError("Source resource unavailable")
        if reference.scheme in {"document", "data"} and len(reference.segments) == 1 and not reference.is_collection:
            return await read_native_document_import(UUID(reference.segments[0]), scope)
        info = await resource_info(ctx, uri)
        resolved_privileges = resource_privileges(info.uri)
        if not resolved_privileges or not await check_privilege(user, list(resolved_privileges), get_db()):
            raise PermissionError("Source resource unavailable")
        if info.is_collection or "read" not in info.capabilities:
            raise ValueError("Select a readable file")
        with TemporaryDirectory(prefix="document-import-") as directory:
            path = Path(directory) / "source"
            result = await materialize_resource(ctx, uri, path, max_bytes=runtime_settings.MEMORY_RESOURCE_MAX_BYTES)
            content = await asyncio.to_thread(path.read_bytes)
            return DocumentImportSource(result.name, result.media_type, content)
