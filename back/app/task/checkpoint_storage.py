"""Update the current Task checkpoint and its attempt archive under their existing row locks."""

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import Text, case, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.sql import ColumnElement
from sqlalchemy import cast as sql_cast
from core import websocket
from core.database import get_db
from app.agent.contracts import ExecutionResult
from .models import Task, TaskAttempt
from . import task_service


def _object(column: ColumnElement[Any]) -> ColumnElement[Any]:
    return case((func.jsonb_typeof(column) == "object", column), else_=sql_cast({}, JSONB))


async def store_checkpoint(
    task: Task, attempt: TaskAttempt | None, payload: Mapping[str, Any],
    result: ExecutionResult | None, base: tuple[int, dict[str, int]] | None,
) -> int:
    db = get_db()
    key = "_agent_run_checkpoint"
    checkpoint: ColumnElement[Any] = sql_cast(dict(payload), JSONB)
    if base is not None and task.revision == base[0]:
        data = dict(payload["data"])
        fields: list[ColumnElement[Any]] = []
        for name, count in base[1].items():
            tail = data.pop(name)[count:]
            old = Task.data[key]["data"][name]
            prefix = func.jsonb_path_query_array(old, sql_cast(f"$[0 to {count - 1}]", JSONPATH))
            fields.append(func.jsonb_build_object(name, prefix.op("||")(sql_cast(tail, JSONB))))
        rebuilt: ColumnElement[Any] = sql_cast(data, JSONB)
        for field in fields:
            rebuilt = rebuilt.op("||")(field)
        header = {k: v for k, v in payload.items() if k != "data"}
        checkpoint = sql_cast(header, JSONB).op("||")(func.jsonb_build_object("data", rebuilt))
    # SQL expressions on the mapped row preserve Task's optimistic revision,
    # audit fields and concurrent Working Set changes without loading Task.data.
    task.data = cast(Any, _object(Task.data.expression).op("||")(func.jsonb_build_object(key, checkpoint)))
    if result is not None:
        task.set_execution_result(result)
    await db.flush()
    revision = task.revision
    if attempt is not None:
        archived = select(Task.data[key]).where(Task.id == task.id).scalar_subquery()
        changes: ColumnElement[Any] = func.jsonb_build_object("agent_checkpoint", archived)
        if result is not None:
            run_id = select(Task.data["_agent_run_identity"]["request_run_id"].astext).where(Task.id == task.id).scalar_subquery()
            changes = changes.op("||")(func.jsonb_build_object("runtime_activity", func.jsonb_build_object(
                "run_id", run_id, "at", sql_cast(datetime.now(timezone.utc).isoformat(), Text)
            )))
        await db.execute(update(TaskAttempt).where(TaskAttempt.id == attempt.id).values(
            data=_object(TaskAttempt.data.expression).op("||")(changes)
        ).execution_options(synchronize_session=False))
    await db.commit()
    if websocket.has_event_interest("task", "update"):
        await task_service.publish_updated(task)
    return revision
