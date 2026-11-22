"""Serialize executor-owned progress with other durable Task updates."""
from __future__ import annotations

from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import select

from app.agent import WorkMilestone, WorkPlan
from app.services import McpToolContext
from core.database import get_db

from .models import Task, TaskStatus


def _merge_changes(
    draft: dict[str, Any], previous: WorkPlan | None, *, allow_revision: bool, notes: list[str],
) -> dict[str, Any]:
    milestones = {item.key: item for item in previous.milestones} if previous else {}
    raw_changes: object = draft.get("milestones", [draft] if "key" in draft else [])
    if isinstance(raw_changes, list):
        changes = cast(list[object], raw_changes)
    else:
        notes.append("Use milestones as a list of changes.")
        changes = []
    if len(changes) > 20:
        notes.append("Only the first 20 changes were considered.")
    for index, raw_change in enumerate(changes[:20], start=1):
        change = cast(dict[str, object], raw_change) if isinstance(raw_change, dict) else {}
        raw_key = change.get("key")
        if not isinstance(raw_key, str) or not raw_key.strip():
            notes.append(f"Milestone {index} needs a key.")
            continue
        key = raw_key.strip()
        existing = milestones.get(key)
        if existing is None and len(milestones) >= 20:
            notes.append(f"Milestone {index} exceeds the 20-milestone limit.")
            continue
        fields = {name: value for name, value in change.items()
                  if name in WorkMilestone.model_fields and value is not None}
        label = key.replace("_", " ").replace("-", " ").strip() or key
        base = existing.model_dump() if existing else {"label": label}
        fields["key"] = key
        state = fields.get("state")
        if isinstance(state, str):
            state = state.strip().lower()
            fields["state"] = state
            if existing and state != existing.state and "observation" not in fields:
                base["observation"] = ""
        try:
            candidate = WorkMilestone.model_validate(base | fields)
        except ValidationError as exc:
            detail = exc.errors(include_input=False, include_context=False, include_url=False)[0]["msg"]
            notes.append(f"Milestone {index}: {detail}.")
            continue
        if existing is not None and not allow_revision:
            if candidate.required != existing.required:
                notes.append(f"Left the required flag unchanged for {key}.")
                candidate = candidate.model_copy(update={"required": existing.required})
                if candidate.state == "skipped" and candidate.required:
                    continue
            if existing.state in {"done", "skipped"} and candidate != existing:
                # A later observation can fill a missing detail without reopening completed work.
                if not existing.observation and candidate.observation:
                    enrichment = existing.model_copy(update={"observation": candidate.observation})
                    if candidate == enrichment:
                        milestones[key] = enrichment
                        continue
                notes.append(f"Preserved completed milestone {key}.")
                continue
        if candidate.state == "doing":
            for other_key, item in milestones.items():
                if other_key != key and item.state == "doing":
                    milestones[other_key] = item.model_copy(update={"state": "pending"})
        milestones[key] = candidate

    next_action = previous.next_action if previous else ""
    if "next_action" in draft:
        if isinstance(draft["next_action"], str) and len(draft["next_action"].strip()) <= 1000:
            next_action = draft["next_action"].strip()
        else:
            notes.append("Kept the next action because the supplied value was invalid.")
    return {
        "milestones": [item.model_dump(mode="json") for item in milestones.values()],
        "next_action": next_action,
    }


async def update_work_plan(
    ctx: McpToolContext, draft: dict[str, Any], *, expected_revision: int | None = None,
    revision_reason: str = "", merge: bool = False,
) -> dict[str, object]:
    if ctx.task_id is None:
        return {"status": "unavailable", "notes": ["Work tracking is available from your current active Task."]}
    db = get_db()
    task = await db.scalar(Task.histo_filter(
        select(Task).where(Task.id == ctx.task_id).with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ))
    if task is None or task.agent_id != ctx.agent_id:
        return {"status": "unavailable", "notes": ["Work tracking is available from your current active Task."]}
    if task.status not in {TaskStatus.DISPATCH, TaskStatus.EXEC} or task.paused or task.cancel_requested:
        return {"status": "unavailable", "notes": ["The current Task is inactive or terminal."]}

    data = dict(task.data or {})
    try:
        work_plan_revision = int(data.get("work_plan_revision", 0))
    except (TypeError, ValueError):
        return {"status": "unavailable", "notes": ["The saved plan has an invalid revision."]}
    saved = data.get("work_plan")
    receipt: dict[str, object] = {
        "task_uri": f"galaris://task/{task.id}", "revision": task.revision,
        "work_plan_revision": work_plan_revision, "work_plan": saved,
    }
    try:
        previous = WorkPlan.model_validate(saved) if saved is not None else None
    except ValidationError:
        return receipt | {"status": "unavailable", "notes": ["The saved plan uses an unsupported format."]}

    if draft.get("schema_version", "galaris.work-plan/v1") != "galaris.work-plan/v1":
        return receipt | {"status": "unchanged", "notes": ["Use the current work plan format."]}
    notes: list[str] = []
    reason = revision_reason.strip()
    allow_revision = expected_revision is not None and bool(reason)
    replacement = expected_revision is not None and not merge
    payload = draft if replacement else _merge_changes(draft, previous, allow_revision=allow_revision, notes=notes)
    if not replacement and not payload["milestones"]:
        return receipt | {"status": "unchanged", "notes": notes or ["Add a milestone key to start tracking."]}
    try:
        plan = WorkPlan.model_validate(payload)
    except ValidationError as exc:
        detail = exc.errors(include_input=False, include_context=False, include_url=False)[0]["msg"]
        return receipt | {"status": "unchanged", "notes": [*notes, detail]}
    payload = plan.model_dump(mode="json")
    if payload == saved:
        return receipt | {"status": "unchanged" if notes else "recorded", "notes": notes}
    if expected_revision is not None and expected_revision != work_plan_revision:
        return receipt | {"status": "unchanged", "notes": [
            "The plan changed. Use the work_plan and work_plan_revision in this receipt for a versioned update.",
        ]}
    if replacement and previous is not None and not allow_revision:
        updated = {item.key: item for item in plan.milestones}
        for item in previous.milestones:
            candidate = updated.get(item.key)
            if item.state in {"done", "skipped"} and candidate != item:
                return receipt | {"status": "unchanged", "notes": [
                    f"Changing completed milestone {item.key} requires a revision reason.",
                ]}
            if candidate is not None and candidate.required != item.required:
                return receipt | {"status": "unchanged", "notes": [
                    f"Changing the required flag for {item.key} requires a revision reason.",
                ]}
    data["work_plan"] = payload
    data["work_plan_revision"] = work_plan_revision + 1
    data["organization"] = "tracked"
    if allow_revision:
        data["work_plan_revision_reason"] = reason[:1000]
    task.data = data
    await db.flush()
    from .task_service import save
    await save(task)
    return receipt | {"status": "recorded", "notes": notes, "revision": task.revision,
                      "work_plan_revision": work_plan_revision + 1, "work_plan": payload}
