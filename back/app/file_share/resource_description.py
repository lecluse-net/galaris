"""Persist acquired text through the resource owner's public Memory contract."""

from uuid import UUID

from app.memory.facade import record_attachment_description

from .resource_contracts import ResourceContext


async def record_resource_description(context: ResourceContext, uri: str, description: str) -> UUID:
    return await record_attachment_description(
        uri, description, agent_id=context.agent_id, task_id=context.task_id,
    )
