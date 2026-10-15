"""Personal classification never changes a Dataset's content or grants."""

from typing import Any
from uuid import UUID
from sqlalchemy import delete, select
from core.database import get_db
from .contracts import DataActor, DatasetNotFoundError, DatasetPermissionError
from .models import DatasetTag, DatasetTagAssignment, DatasetAppearance
from . import service


def user(actor: DataActor) -> int:
    if isinstance(actor, int):
        raise DatasetPermissionError("Personal classification requires a human account")
    return actor.user_id


async def tags(actor: DataActor) -> list[dict[str, Any]]:
    rows = await get_db().scalars(select(DatasetTag).where(DatasetTag.user_id == user(actor)).order_by(DatasetTag.position, DatasetTag.id).limit(500))
    return [{"id": str(item.id), "name": item.name, "parent_id": str(item.parent_id) if item.parent_id else None,
        "position": item.position, "icon": item.icon} for item in rows]


async def save_tag(actor: DataActor, *, name: str, parent_id: UUID | None = None) -> DatasetTag:
    user_id = user(actor)
    if not name.strip() or len(name) > 100:
        raise ValueError("A tag requires a name of at most 100 characters")
    if len(await tags(actor)) >= 500:
        raise ValueError("At most 500 personal Dataset tags are supported")
    if parent_id is not None and await get_db().scalar(select(DatasetTag.id).where(DatasetTag.id == parent_id, DatasetTag.user_id == user_id)) is None:
        raise DatasetNotFoundError("Parent tag not found")
    item = DatasetTag(user_id=user_id, name=name.strip(), parent_id=parent_id)
    get_db().add(item)
    await get_db().flush()
    return item


async def classify(identity: UUID, actor: DataActor, *, tags: list[UUID], icon: str | None = None, position: int = 0) -> None:
    user_id = user(actor)
    await service.record(identity, actor)
    if len(tags) > 100 or len(set(tags)) != len(tags):
        raise ValueError("Select at most 100 distinct personal tags")
    selected = set(await get_db().scalars(select(DatasetTag.id).where(DatasetTag.id.in_(tags), DatasetTag.user_id == user_id)))
    if selected != set(tags):
        raise DatasetNotFoundError("Personal tag not found")
    # Lock the resource before replacing this user's associations.
    await service.record(identity, actor, lock=True)
    own_tags = select(DatasetTag.id).where(DatasetTag.user_id == user_id)
    await get_db().execute(delete(DatasetTagAssignment).where(DatasetTagAssignment.dataset_id == identity, DatasetTagAssignment.tag_id.in_(own_tags)))
    for tag_id in tags:
        get_db().add(DatasetTagAssignment(dataset_id=identity, tag_id=tag_id))
    appearance = await get_db().scalar(select(DatasetAppearance).where(DatasetAppearance.dataset_id == identity, DatasetAppearance.user_id == user_id))
    if appearance is None:
        appearance = DatasetAppearance(dataset_id=identity, user_id=user_id)
        get_db().add(appearance)
    appearance.icon, appearance.position = icon, position
    await get_db().flush()
