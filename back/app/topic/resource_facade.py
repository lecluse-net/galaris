"""Topic metadata for the File Sharing resource provider."""

from uuid import UUID

from sqlalchemy import or_, select

from app.connection.facade import has_active_tool_connection
from core.database import get_db

from . import service
from .models import Topic
from .schemas import TopicRead


async def require_topic_connection(agent_id: int) -> None:
    if not await has_active_tool_connection(agent_id, "topic"):
        raise PermissionError("An active topic connection is required to access Topics.")


async def read_topic_resource(identifier: UUID, agent_id: int) -> dict[str, object] | None:
    await require_topic_connection(agent_id)
    topic = await service.get(identifier)
    return topic.model_dump(mode="json") if topic is not None else None


async def list_topic_resources(agent_id: int, query: str, offset: int, limit: int) -> list[dict[str, object]]:
    if not await has_active_tool_connection(agent_id, "topic"):
        return []
    statement = Topic.histo_filter(select(Topic))
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = statement.where(or_(
            Topic.title.ilike(pattern, escape="\\"),
            Topic.description.ilike(pattern, escape="\\"),
        ))
    rows = await get_db().scalars(statement.order_by(Topic.title, Topic.id).offset(offset).limit(limit))
    return [TopicRead.model_validate(topic).model_dump(mode="json") for topic in rows]
