"""Task-owned persistence of scopes admitted by the agent domain."""
from uuid import uuid4
from collections.abc import Sequence
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import SCOPE_KEY, admitted_scope, parse_scope
from core.database import get_db
from .models import Task


async def initialize_scope(task: Task, *, re_admission: bool = False,
    db: AsyncSession | None = None, source_reference: str | None = None,
    resolved_write_targets: Sequence[str] = ()) -> None:
    task.id = task.id or uuid4()
    data = dict(task.data or {})
    previous = parse_scope(data) if re_admission else None
    data.pop(SCOPE_KEY, None)  # Never trust client/model-supplied grants.
    data.pop("scope_preflights", None)
    lineage_id = task.parent_id or (task.source_task_id if not re_admission else None)
    if lineage_id is not None:
        parent = await (db if db is not None else get_db()).get(Task, lineage_id)
        scope = parse_scope(parent.data or {}) if parent is not None else None
    else:
        scope = admitted_scope(task.id, str(data.get("_original_demand") or task.objective or ""),
            delivery_target=f"messenger://room/{task.message_group_id}" if task.message_group_id else None,
            source_reference=source_reference, resolved_write_targets=resolved_write_targets)
        if previous is not None:
            scope = scope.model_copy(update={"revision": previous.revision + 1})
    if scope is not None:
        data[SCOPE_KEY] = scope.model_dump(mode="json")
    task.data = data
