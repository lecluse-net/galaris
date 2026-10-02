"""Persist acquired text through the resource owner's public Memory contract."""

from uuid import UUID
import hashlib

from sqlalchemy import select
from core.database import get_db

from app.memory.facade import record_attachment_description
from app.memory import catalogue_projection_write

from .catalogue import observation_scope, observe_descriptors, descriptor_version
from .enrichment import apply_enrichment
from .models import FileCatalogEntry
from .resource_contracts import ResourceContext


async def record_resource_description(context: ResourceContext, uri: str, description: str) -> UUID:
    scope = await observation_scope(context, uri)
    if scope is not None:
        from .resource_service import resource_info
        from .resource_observation import suspend_observations
        with suspend_observations():
            descriptor = await resource_info(context, uri)
        db = get_db()
        async with catalogue_projection_write():
            async with db.begin_nested():
                await observe_descriptors(scope, [descriptor])
                entry = await db.scalar(select(FileCatalogEntry).where(
                    FileCatalogEntry.connection_id == scope.connection_id,
                    FileCatalogEntry.binding_stamp == scope.stamp,
                    FileCatalogEntry.runtime == scope.runtime,
                    FileCatalogEntry.uri_key == hashlib.sha256(descriptor.uri.encode()).hexdigest(),
                ))
                if entry is None or entry.memory_item_id is None:
                    raise PermissionError("Resource binding changed")
                await apply_enrichment(entry.id, descriptor_version(entry.descriptor), description)
                item_id = entry.memory_item_id
            await db.commit()
        return item_id
    return await record_attachment_description(
        uri, description, agent_id=context.agent_id, task_id=context.task_id,
    )
