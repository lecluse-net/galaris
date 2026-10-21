"""Dataset library filters and personal placements, independent of Memory folders."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Select, func, literal, select
from sqlalchemy.sql.elements import ColumnElement

from app.share import sharing_directory
from core.database import get_db
from .access import accessible_clause
from .contracts import DataActor
from .models import Dataset, DatasetAppearance, DatasetTag, DatasetTagAssignment


class LibraryFilters(BaseModel):
    classification: Literal["all", "unclassified", "classified"] = "all"
    keyword: str | None = Field(default=None, max_length=200)
    owner_kind: Literal["agent", "user"] | None = None
    owner: int | None = Field(default=None, gt=0)
    created_from: datetime | None = None
    created_until: datetime | None = None
    updated_from: datetime | None = None
    updated_until: datetime | None = None
    sort_by: Literal["position", "title", "created_at", "updated_at"] = "updated_at"
    sort_desc: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> "LibraryFilters":
        for start, end in ((self.created_from, self.created_until), (self.updated_from, self.updated_until)):
            if start is not None and start.tzinfo is None or end is not None and end.tzinfo is None:
                raise ValueError("Date filters require a timezone")
            if start is not None and end is not None and start >= end:
                raise ValueError("Date interval is empty")
        return self


async def filter_statement(statement: Select[tuple[Dataset]], actor: DataActor, filters: LibraryFilters) -> Select[tuple[Dataset]]:
    if filters.classification != "all":
        from .organization import user
        assignments = select(DatasetTagAssignment.dataset_id).join(DatasetTag).where(DatasetTag.user_id == user(actor))
        classified = Dataset.id.in_(assignments)
        statement = statement.where(classified if filters.classification == "classified" else ~classified)
    if filters.keyword:
        statement = statement.where(Dataset.keywords.contains([filters.keyword]))
    if filters.owner_kind:
        owner = Dataset.owner_agent_id if filters.owner_kind == "agent" else Dataset.owner_user_id
        statement = statement.where(owner == filters.owner if filters.owner is not None else owner.is_not(None))
    for column, start, end in ((Dataset.created_at, filters.created_from, filters.created_until),
        (func.coalesce(Dataset.updated_at, Dataset.created_at), filters.updated_from, filters.updated_until)):
        if start is not None:
            statement = statement.where(column >= start)
        if end is not None:
            statement = statement.where(column < end)
    return statement


def placement(actor: DataActor, tag_id: UUID | None) -> ColumnElement[int]:
    if isinstance(actor, int):
        return literal(0)
    if tag_id:
        return func.coalesce(select(DatasetTagAssignment.position).where(
            DatasetTagAssignment.dataset_id == Dataset.id, DatasetTagAssignment.tag_id == tag_id).scalar_subquery(), 0)
    return func.coalesce(select(DatasetAppearance.position).where(
        DatasetAppearance.dataset_id == Dataset.id, DatasetAppearance.user_id == actor.user_id).scalar_subquery(), 0)


async def decorate(items: list[dict[str, Any]], actor: DataActor) -> None:
    if isinstance(actor, int) or not items:
        return
    identities = [UUID(item["id"]) for item in items]
    assignments = list((await get_db().execute(select(DatasetTagAssignment.dataset_id, DatasetTagAssignment.tag_id).join(
        DatasetTag).where(DatasetTag.user_id == actor.user_id, DatasetTagAssignment.dataset_id.in_(identities)))).all())
    appearances = {str(item.dataset_id): item for item in await get_db().scalars(select(DatasetAppearance).where(
        DatasetAppearance.user_id == actor.user_id, DatasetAppearance.dataset_id.in_(identities)))}
    for item in items:
        item["tag_ids"] = [str(tag) for dataset, tag in assignments if str(dataset) == item["id"]]
        item["icon"] = appearances[item["id"]].icon if item["id"] in appearances else None


async def facets(actor: DataActor) -> dict[str, Any]:
    from .organization import user
    owners = (await get_db().execute(select(Dataset.owner_agent_id, Dataset.owner_user_id).where(accessible_clause(actor)).distinct())).all()
    keys = {("agent", agent) if agent is not None else ("user", human) for agent, human in owners}
    directory = await sharing_directory(owner_agent_id=None, owner_user_id=user(actor))
    choices = [*directory.options, *([directory.owner] if directory.owner else [])]
    keywords = await get_db().scalars(select(func.jsonb_array_elements_text(Dataset.keywords)).where(accessible_clause(actor)).distinct())
    return {"owners": [item.model_dump() for item in choices if (item.kind, item.id) in keys],
        "keywords": sorted(set(keywords)), "current_user_id": user(actor)}
