"""Dataset references persisted in accessible Process runs."""

from typing import Any
from sqlalchemy import String, cast, func, or_, select
from app.agent import AgentManagementScope
from core.database import get_db
from core.authorize import check_privilege
from core.user import get_user_record
from .models import ProcessDefinition, ProcessRun


async def find_dataset_run_usages(uris: tuple[str, ...], actor: AgentManagementScope, offset: int, limit: int) -> dict[str, Any]:
    if not await check_privilege(await get_user_record(actor.user_id), ["PROCESS_READ", "PROCESS_ADMIN"], get_db()):
        return {"total": 0, "items": []}
    query = select(ProcessRun, ProcessDefinition.label).join(ProcessDefinition, ProcessDefinition.id == ProcessRun.process_id).where(
        or_(*(cast(ProcessRun.launch_snapshot, String).contains(uri, autoescape=True) for uri in uris)))
    if actor.agent_ids is not None:
        query = query.where(ProcessRun.launcher_agent_id.in_(actor.agent_ids))
    total = await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0
    rows: list[tuple[ProcessRun, str]] = list((await get_db().execute(query.order_by(ProcessRun.created_at.desc(), ProcessRun.id).offset(offset).limit(limit))).tuples().all()) if limit else []
    return {"total": total, "items": [{"id": f"run:{run.id}", "label": label, "relation": "process_run",
        "url": "/process",
        "last_used_at": run.created_at.isoformat()} for run, label in rows]}
