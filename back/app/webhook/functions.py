"""Webhook application services."""
from typing import Dict, Any, Optional, cast
import hashlib
import json
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from core.database import get_db
from app.task import TaskCreate, TaskStatus, task_service
from app.tools import tool_service
from app.connection.models import Connection as ConnectionModel, ConnectionParam
from app.agent.models import Agent as AgentModel
from app.tools.schemas import Tool
from app.task import runner
from core.i18n import default_language, is_supported, render_prompt, t


class WebhookIdentityConflict(ValueError):
    """An emitter reused a delivery identity for a different payload."""


async def _get_tool_by_name(tool_name: str) -> Optional[Tool]:  # pyright: ignore[reportUnusedFunction]
    """Resolve a tool from the name embedded in a webhook URL."""
    record = await tool_service.get_tool_record(tool_name)
    if record is None:
        return None
    from app.tools.tool_service import _to_internal  # pyright: ignore[reportPrivateUsage]
    return _to_internal(record)


async def webhook_make_task(
    tool_name: str,
    data: Dict[str, Any],
    *, delivery_id: str | None = None,
) -> str:
    raw_language = str(data.get("language") or "").strip().lower()
    language = raw_language if is_supported(raw_language) else default_language()

    if not tool_name:
        raise ValueError(t("webhook.errors.tool_name_required", language))

    tool_record = await tool_service.get_tool_record(tool_name)
    if not tool_record:
        raise LookupError(
            render_prompt(
                t("webhook.errors.tool_not_found", language),
                tool_name=tool_name,
            )
        )

    from app.tools.tool_service import _to_internal  # pyright: ignore[reportPrivateUsage]
    tool: Tool = _to_internal(tool_record)

    if not tool.listener or not tool.listener.connection_key:
        raise LookupError(
            render_prompt(
                t("webhook.errors.listener_missing", language),
                tool_name=tool_name,
            )
        )

    connection_key = tool.listener.connection_key
    connection_value: Optional[Any] = data.get(connection_key)
    if not connection_value:
        raise ValueError(
            render_prompt(
                t("webhook.errors.required_field_missing", language),
                field=connection_key,
            )
        )

    from sqlalchemy.engine import Result
    from sqlalchemy.sql import Select
    stmt: Select[Any] = (
        select(ConnectionModel, AgentModel)
        .options(selectinload(AgentModel.title))
        .join(ConnectionParam)
        .join(AgentModel, AgentModel.id == ConnectionModel.agent_id)
        .where(
            ConnectionModel.tool_id == tool_record.id,
            ConnectionParam.param_name == connection_key,
            ConnectionParam.param_value == str(connection_value),
            ConnectionModel.active == True
        )
    )
    result: Result[Any] = await get_db().execute(stmt)
    row = result.one_or_none()

    if row is None:
        raise LookupError(
            render_prompt(
                t("webhook.errors.connection_not_found", language),
                tool_name=tool_name,
                key=connection_key,
                value=connection_value,
            )
        )
    connection, agent = row
    if delivery_id is not None and (not delivery_id.strip() or len(delivery_id) > 255):
        raise ValueError("Idempotency-Key must contain 1 to 255 characters")
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    identity = (
        f"webhook:{tool_record.id}:{connection.id}:{delivery_id}"
        if delivery_id is not None else None
    )
    label: str
    objective: str

    if tool.task:
        rendered_task = tool.task.render(data)  # type: ignore[call-arg]
        label = rendered_task.label or data.get("label") or render_prompt(
            t("webhook.task.label", language),
            source=tool.label or tool_name,
        )
        first_name = cast(str, agent.first_name)  # type: ignore[arg-type]
        last_name = cast(str, agent.last_name)  # type: ignore[arg-type]
        objective = rendered_task.objective or render_prompt(
            t("webhook.task.objective", language),
            source=tool_name,
            agent_name=f"{first_name} {last_name}",
        )
    else:
        label = data.get("label") or render_prompt(
            t("webhook.task.label", language),
            source=tool.label or tool_name,
        )
        first_name = cast(str, agent.first_name)  # type: ignore[arg-type]
        last_name = cast(str, agent.last_name)  # type: ignore[arg-type]
        objective = render_prompt(
            t("webhook.task.objective", language),
            source=tool_name,
            agent_name=f"{first_name} {last_name}",
        )

    task_data = TaskCreate(
        agent_id=cast(int, agent.id),  # type: ignore[arg-type]
        label=label,
        objective=objective,
        status=TaskStatus.CREATE,
        ai=True,
        cost=0.0,
        data={"language": language, **({"webhook_fingerprint": fingerprint} if identity else {})},
    )
    new_task = await task_service.create(task_data, idempotency_key=identity)
    if identity and (new_task.data or {}).get("webhook_fingerprint") != fingerprint:
        raise WebhookIdentityConflict("Idempotency-Key already belongs to a different webhook payload")
    runner.go_next(new_task.id)
    return str(new_task.id)
