"""Personal classification never changes a Dataset's content or grants."""

from typing import Any
from uuid import UUID
from sqlalchemy import delete, func, select
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
    await lock_tree(actor)
    if not name.strip() or len(name) > 100:
        raise ValueError("A tag requires a name of at most 100 characters")
    if len(await tags(actor)) >= 500:
        raise ValueError("At most 500 personal Dataset tags are supported")
    if parent_id is not None and await get_db().scalar(select(DatasetTag.id).where(DatasetTag.id == parent_id, DatasetTag.user_id == user_id)) is None:
        raise DatasetNotFoundError("Parent tag not found")
    parent = await require_tag(actor, parent_id) if parent_id else None
    item = DatasetTag(user_id=user_id, name=name.strip(), parent_id=parent_id,
        icon=parent.icon if parent else None, position=await next_position(actor, parent_id))
    get_db().add(item)
    await get_db().flush()
    return item


async def classify(identity: UUID, actor: DataActor, *, tags: list[UUID], icon: str | None = None, position: int = 0) -> None:
    user_id = user(actor)
    await lock_tree(actor)
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


async def lock_tree(actor: DataActor) -> None:
    await get_db().execute(select(func.pg_advisory_xact_lock(1195656264, user(actor))))


async def require_tag(actor: DataActor, identity: UUID) -> DatasetTag:
    item = await get_db().scalar(select(DatasetTag).where(DatasetTag.id == identity,
        DatasetTag.user_id == user(actor)).execution_options(populate_existing=True))
    if item is None:
        raise DatasetNotFoundError("Personal Dataset folder not found")
    return item


async def next_position(actor: DataActor, parent_id: UUID | None) -> int:
    folders = await get_db().scalar(select(func.max(DatasetTag.position)).where(
        DatasetTag.user_id == user(actor), DatasetTag.parent_id == parent_id)) or 0
    datasets = await get_db().scalar(select(func.max(DatasetTagAssignment.position)).where(
        DatasetTagAssignment.tag_id == parent_id)) if parent_id else 0
    return max(folders, datasets or 0) + 1


async def update_tag(actor: DataActor, identity: UUID, *, name: str, parent_id: UUID | None,
                     icon: str | None) -> None:
    await lock_tree(actor)
    item = await require_tag(actor, identity)
    if not name.strip() or len(name) > 100:
        raise ValueError("A folder requires a name of at most 100 characters")
    ancestor = parent_id
    while ancestor is not None:
        if ancestor == identity:
            raise ValueError("A folder cannot contain itself")
        ancestor = (await require_tag(actor, ancestor)).parent_id
    if item.parent_id != parent_id:
        item.position = await next_position(actor, parent_id)
    item.name, item.parent_id, item.icon = name.strip(), parent_id, icon


async def remove_tag(actor: DataActor, identity: UUID, *, confirmed: bool = False) -> dict[str, object]:
    await lock_tree(actor)
    await require_tag(actor, identity)
    rows = list(await get_db().scalars(select(DatasetTag).where(DatasetTag.user_id == user(actor))))
    branch = {identity}
    while children := {item.id for item in rows if item.parent_id in branch} - branch:
        branch.update(children)
    affected = list(await get_db().scalars(select(DatasetTagAssignment.dataset_id).where(
        DatasetTagAssignment.tag_id.in_(branch)).distinct()))
    result: dict[str, object] = {"deleted": False, "tag_count": len(branch), "dataset_count": len(affected)}
    if not confirmed and (affected or len(branch) > 1):
        return result
    own = select(DatasetTag.id).where(DatasetTag.user_id == user(actor))
    await get_db().execute(delete(DatasetTagAssignment).where(
        DatasetTagAssignment.dataset_id.in_(affected), DatasetTagAssignment.tag_id.in_(own)))
    for item in rows:
        if item.id in branch:
            item.soft_delete()
    result["deleted"] = True
    return result


async def move(actor: DataActor, *, kind: str, identity: UUID, parent_id: UUID | None,
               anchor_kind: str | None = None, anchor_id: UUID | None = None, after: bool = True) -> None:
    """Move only the caller's placement; content, grants and revisions stay intact."""
    await lock_tree(actor)
    if parent_id:
        await require_tag(actor, parent_id)
    if anchor_id is not None and anchor_kind == "dataset":
        await service.record(anchor_id, actor)
    if kind == "tag":
        folder = await require_tag(actor, identity)
        await update_tag(actor, identity, name=folder.name, parent_id=parent_id, icon=folder.icon)
        moving: DatasetTag | DatasetTagAssignment | DatasetAppearance = folder
    else:
        await service.record(identity, actor)
        own = select(DatasetTag.id).where(DatasetTag.user_id == user(actor))
        await get_db().execute(delete(DatasetTagAssignment).where(
            DatasetTagAssignment.dataset_id == identity, DatasetTagAssignment.tag_id.in_(own)))
        if parent_id:
            moving = DatasetTagAssignment(dataset_id=identity, tag_id=parent_id)
            get_db().add(moving)
        else:
            appearance = await get_db().scalar(select(DatasetAppearance).where(
                DatasetAppearance.dataset_id == identity, DatasetAppearance.user_id == user(actor)))
            moving = appearance or DatasetAppearance(dataset_id=identity, user_id=user(actor))
            get_db().add(moving)
    moving.position = await next_position(actor, parent_id)
    await get_db().flush()
    folders = list(await get_db().scalars(select(DatasetTag).where(DatasetTag.user_id == user(actor), DatasetTag.parent_id == parent_id)))
    placements: list[DatasetTag | DatasetTagAssignment | DatasetAppearance] = list(folders)
    if parent_id:
        placements.extend(await get_db().scalars(select(DatasetTagAssignment).where(DatasetTagAssignment.tag_id == parent_id)))
    else:
        from .models import Dataset
        from .access import accessible_clause
        own_tags = select(DatasetTag.id).where(DatasetTag.user_id == user(actor))
        classified = select(DatasetTagAssignment.dataset_id).where(DatasetTagAssignment.tag_id.in_(own_tags))
        unclassified = list(await get_db().scalars(select(Dataset.id).where(
            accessible_clause(actor), ~Dataset.id.in_(classified))))
        existing = set(await get_db().scalars(select(DatasetAppearance.dataset_id).where(DatasetAppearance.user_id == user(actor))))
        for dataset_id in unclassified:
            if dataset_id not in existing:
                get_db().add(DatasetAppearance(dataset_id=dataset_id, user_id=user(actor), position=0))
        await get_db().flush()
        placements.extend(await get_db().scalars(select(DatasetAppearance).where(DatasetAppearance.user_id == user(actor))))
    placements.sort(key=lambda item: (item.position, str(item.id)))
    placements = [item for item in placements if item is not moving]
    index = len(placements)
    if anchor_id is not None:
        matches = [i for i, item in enumerate(placements) if
            ("tag" if isinstance(item, DatasetTag) else "dataset") == anchor_kind
            and (item.id if isinstance(item, DatasetTag) else item.dataset_id) == anchor_id]
        if not matches:
            raise DatasetNotFoundError("Folder placement not found")
        index = matches[0] + int(after)
    placements.insert(index, moving)
    for index, item in enumerate(placements):
        item.position = index + 1


async def sort_folder(actor: DataActor, identity: UUID, *, descending: bool = False) -> None:
    await lock_tree(actor)
    await require_tag(actor, identity)
    folders = list(await get_db().scalars(select(DatasetTag).where(
        DatasetTag.user_id == user(actor), DatasetTag.parent_id == identity)))
    from .models import Dataset
    assignments = list((await get_db().execute(select(DatasetTagAssignment, Dataset.title).join(
        Dataset, Dataset.id == DatasetTagAssignment.dataset_id).where(
        DatasetTagAssignment.tag_id == identity, service.accessible_clause(actor)))).all())
    values: list[tuple[DatasetTag | DatasetTagAssignment, str]] = [(item, item.name) for item in folders]
    values.extend((item, title) for item, title in assignments)
    values.sort(key=lambda pair: (not isinstance(pair[0], DatasetTag), pair[1].casefold(), str(pair[0].id)), reverse=descending)
    for index, (item, _) in enumerate(values):
        item.position = index + 1
    await get_db().flush()
