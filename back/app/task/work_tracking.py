"""Serialize executor-owned progress with other durable Task updates."""
from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import select

from app.agent import WorkPlan, WorkPlanInput
from app.services import McpToolContext, RecoverableToolError
from app.services.contracts import ToolCallRejectedError
from core.database import get_db

from .models import Task, TaskStatus


class WorkTrackingRejected(RecoverableToolError, ToolCallRejectedError):
    """A model-safe precondition failure before any progress is changed."""


async def update_work_plan(
    ctx: McpToolContext, draft: WorkPlanInput, *, expected_revision: int,
    revision_reason: str = "", merge: bool = False,
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
    if task.status not in {TaskStatus.DISPATCH, TaskStatus.EXEC} or task.paused or task.cancel_requested:
        raise WorkTrackingRejected("An inactive or terminal Task cannot update work tracking")
    data = dict(task.data or {})
    # Runtime checkpoints and activity updates advance Task.revision independently.
    # Serialize writers on the Task row, but compare only the progress they inspected.
    work_plan_revision = int(data.get("work_plan_revision", 0))
    previous = WorkPlan.model_validate(data["work_plan"]) if isinstance(data.get("work_plan"), dict) else None
    payload = draft.model_dump(mode="json")
    if merge and previous is not None:
        changes = {milestone.key: milestone for milestone in draft.milestones}
        if len(changes) != len(draft.milestones):
            raise WorkTrackingRejected("Invalid plan: Milestone keys must be unique")
        milestones = {milestone.key: milestone for milestone in previous.milestones}
        milestones.update(changes)
        payload["milestones"] = list(milestones.values())
        if "next_action" not in draft.model_fields_set:
            payload["next_action"] = previous.next_action
    try:
        plan = WorkPlan.model_validate(payload)
    except ValidationError as exc:
        detail = exc.errors(include_input=False, include_context=False, include_url=False)[0]["msg"]
        raise WorkTrackingRejected(f"Invalid plan: {detail}") from exc
    payload = plan.model_dump(mode="json")
    if data.get("work_plan") == payload:
        return {"task_uri": f"galaris://task/{task.id}", "revision": task.revision,
                "work_plan_revision": work_plan_revision, "work_plan": payload}
    if work_plan_revision != expected_revision:
        raise WorkTrackingRejected(
            f"Work plan revision changed: sent {expected_revision}, current work_plan_revision={work_plan_revision}. "
            "Call task_get, reconcile your changes with its current work_plan, and use the returned "
            "work_plan_revision as expected_revision."
        )
    if previous is not None:
        updated = {item.key: item for item in plan.milestones}
        changed_completed = [
            item.key for item in previous.milestones
            if item.state in {"done", "skipped"} and updated.get(item.key) != item
        ]
        if changed_completed and not revision_reason.strip():
            raise WorkTrackingRejected(
                "Changing completed work requires an explicit revision reason. "
                f"Affected keys: {', '.join(changed_completed)}. "
                "For unrelated changes, use merge=true and omit those keys."
            )
        if any(item.key in updated and item.required != updated[item.key].required
               for item in previous.milestones) and not revision_reason.strip():
            raise WorkTrackingRejected("Changing required status requires an explicit revision reason")
    data["work_plan"] = payload
    data["work_plan_revision"] = work_plan_revision + 1
    data["organization"] = "tracked"
    if revision_reason.strip():
        data["work_plan_revision_reason"] = revision_reason.strip()[:1000]
    task.data = data
    await db.flush()
    from .task_service import save
    await save(task)
    return {"task_uri": f"galaris://task/{task.id}", "revision": task.revision,
            "work_plan_revision": work_plan_revision + 1, "work_plan": payload}
