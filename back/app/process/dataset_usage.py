"""Dataset references persisted in accessible Process runs."""

from typing import Any
from sqlalchemy import String, cast, func, or_, select
from app.agent import AgentManagementScope
from core.database import get_db
from core.authorize import check_privilege
from core.user import get_user_record
from .models import ProcessDefinition, ProcessRun, ProcessRunFile
from .native_runs import readable_run_clause
from .native_access import accessible_clause


async def find_dataset_definition_usages(uris: tuple[str, ...], actor: AgentManagementScope, offset: int, limit: int) -> dict[str, Any]:
    if not await check_privilege(await get_user_record(actor.user_id), ["PROCESS_READ", "PROCESS_EDIT", "PROCESS_ADMIN"], get_db()):
        return {"total": 0, "items": []}
    query = select(ProcessDefinition).where(accessible_clause(actor),
        or_(*(ProcessDefinition.bpmn_xml.contains(uri, autoescape=True) for uri in uris)))
    total = await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(await get_db().scalars(query.order_by(ProcessDefinition.id).offset(offset).limit(limit))) if limit else []
    return {"total": total, "items": [{"id": f"process:{record.id}", "label": record.label,
        "relation": "process_definition", "url": f"/process/internal/{record.code}", "last_used_at": None} for record in rows]}


async def find_dataset_run_usages(uris: tuple[str, ...], actor: AgentManagementScope, offset: int, limit: int) -> dict[str, Any]:
    if not await check_privilege(await get_user_record(actor.user_id), ["PROCESS_READ", "PROCESS_ADMIN"], get_db()):
        return {"total": 0, "items": []}
    query = select(ProcessRun, ProcessDefinition.label).join(ProcessDefinition, ProcessDefinition.id == ProcessRun.process_id).where(
        readable_run_clause(actor), or_(
            *(cast(ProcessRun.launch_snapshot, String).contains(uri, autoescape=True) for uri in uris),
            *(cast(ProcessRun.data, String).contains(uri, autoescape=True) for uri in uris),
            select(ProcessRunFile.id).where(ProcessRunFile.run_id == ProcessRun.id,
                ProcessRunFile.uri.in_(uris)).exists()))
    total = await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0
    rows: list[tuple[ProcessRun, str]] = list((await get_db().execute(query.order_by(ProcessRun.created_at.desc(), ProcessRun.id).offset(offset).limit(limit))).tuples().all()) if limit else []
    return {"total": total, "items": [{"id": f"run:{run.id}", "label": label, "relation": "process_run",
        "url": f"/process/internal/run/{run.id}",
        "last_used_at": run.created_at.isoformat()} for run, label in rows]}
