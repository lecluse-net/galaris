"""Serialize executor-owned progress with other durable Task updates."""
from __future__ import annotations

from sqlalchemy import select

from app.agent import WorkPlan
from app.tools import McpToolContext
from core.database import get_db

from .models import Task, TaskStatus


async def update_work_plan(
    ctx: McpToolContext, plan: WorkPlan, *, expected_revision: int,
    revision_reason: str = "",
) -> dict[str, object]:
    if ctx.task_id is None:
        raise PermissionError("Work tracking requires the current Task context")
    db = get_db()
    task = await db.scalar(Task.histo_filter(
        select(Task).where(Task.id == ctx.task_id).with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ))
    if task is None or task.agent_id != ctx.agent_id:
        raise PermissionError("Only the executing agent can update its own work tracking")
    if task.status not in {TaskStatus.DISPATCH, TaskStatus.EXEC} or task.paused:
        raise ValueError("An inactive or terminal Task cannot update work tracking")
    data = dict(task.data or {})
    payload = plan.model_dump(mode="json")
    if data.get("work_plan") == payload:
        return {"task_uri": f"galaris://task/{task.id}", "revision": task.revision, "work_plan": payload}
    if task.revision != expected_revision:
        raise ValueError("Task revision changed; read task_get before updating work tracking")
    if isinstance(data.get("work_plan"), dict):
        previous = WorkPlan.model_validate(data["work_plan"])
        updated = {item.key: item for item in plan.milestones}
        if any(item.state == "done" and updated.get(item.key) != item for item in previous.milestones):
            if not revision_reason.strip():
                raise ValueError("Changing completed work requires an explicit revision reason")
    data["work_plan"] = payload
    data["organization"] = "tracked"
    if revision_reason.strip():
        data["work_plan_revision_reason"] = revision_reason.strip()[:1000]
    task.data = data
    await db.flush()
    from .task_service import save
    await save(task)
    return {"task_uri": f"galaris://task/{task.id}", "revision": task.revision, "work_plan": payload}
