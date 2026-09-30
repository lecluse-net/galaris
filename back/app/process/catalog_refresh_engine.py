"""Resumable, bounded ToolAdmin catalogue reconciliation through canonical Process."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .schemas import (
    EngineError, EngineProcessDefinition, EngineRunReference, EngineRunSnapshot,
    EngineStartResult, ProcessEngineHealth, ProcessStartPayload,
)
from .interface import engine_checkpoint, ensure_integrated_definition
from . import process_service
from core.database import release_db_transaction

from app.tools.facade import AdministrationContext, AdministrationError


class RefreshAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_ids: list[int] = Field(max_length=10000)
    function_name: str


class CatalogRefreshEngine:
    code = "tool_admin"
    supports_cancel = True
    cancel_mode = "supported"
    start_timeout_seconds = 30.0
    refresh_timeout_seconds = 30.0

    async def health(self) -> ProcessEngineHealth:
        return ProcessEngineHealth(tool_code=self.code, status="healthy", reachable=True,
            authenticated=True, supports_cancel=True, cancel_mode="supported",
            message="Integrated ToolAdmin catalogue reconciliation", checked_at=datetime.now(timezone.utc))

    async def sync_definitions(self) -> list[EngineProcessDefinition]:
        return []

    async def prepare_input(self, agent_id: int, workflow_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        if workflow_id != f"tool_admin:{agent_id}:catalog_refresh":
            raise PermissionError("Invalid ToolAdmin workflow")
        admission = RefreshAdmission.model_validate(input_data)
        if admission.function_name not in {
            "tool_admin_catalog_refresh", "tool_admin_create", "tool_admin_update", "tool_admin_delete",
            "tool_admin_global_params_set", "tool_admin_conversation_set", "tool_admin_function_set",
            "tool_admin_connection_create", "tool_admin_connection_update", "tool_admin_connection_delete",
            "tool_admin_connection_params_set", "tool_admin_connection_param_delete", "tool_admin_connection_function_set",
        } or any(identifier <= 0 for identifier in admission.agent_ids):
            raise PermissionError("Invalid catalogue refresh admission")
        await AdministrationContext(agent_id=agent_id, function_name=admission.function_name).require()
        admission.agent_ids = sorted(set(admission.agent_ids))
        return admission.model_dump()

    async def start_run(self, engine_process_id: str, run: EngineRunReference, payload: ProcessStartPayload) -> EngineStartResult:
        data = await engine_checkpoint(run.id, self.code)
        if engine_process_id != f"tool_admin:{data['agent_id']}:catalog_refresh":
            raise PermissionError("Invalid ToolAdmin workflow")
        # All progress is persisted by get_run; duplicate starts have no effect.
        return EngineStartResult(accepted=True, engine_run_id=str(run.id))

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        from app.tools.facade import administration

        data = await engine_checkpoint(run.id, self.code)
        admission = RefreshAdmission.model_validate(data["input"])
        metadata = data["metadata"]
        completed = list(metadata.get("completed_agent_ids", []))
        failed = list(metadata.get("failed_agent_ids", []))
        remaining = [identifier for identifier in admission.agent_ids if identifier not in completed]
        if metadata.get("cancelled"):
            return EngineRunSnapshot(status="cancelled", output={"complete": False, "remaining_agent_ids": remaining})
        if remaining and not data["terminal"]:
            try:
                actor = AdministrationContext(agent_id=data["agent_id"], function_name=admission.function_name)
                await actor.require()
            except AdministrationError:
                return EngineRunSnapshot(status="error", output={"complete": False, "remaining_agent_ids": remaining},
                    error=EngineError(code="access_denied", message="ToolAdmin delegation was revoked before reconciliation."))
            await release_db_transaction()
            result = await administration.refresh_batch(remaining[:1], actor=actor)
            identifier = remaining.pop(0)
            completed.append(identifier)
            if not result["complete"]:
                failed.append(identifier)
            await engine_checkpoint(run.id, self.code, {
                "completed_agent_ids": completed, "failed_agent_ids": failed,
            })
        output = {"complete": not remaining and not failed, "agents_refreshed": len(completed) - len(failed),
                  "failed_agent_ids": failed, "remaining_agent_ids": remaining}
        return EngineRunSnapshot(status="running" if remaining else "error" if failed else "success", output=output,
            error=EngineError(code="catalog_refresh_partial", message="Retry catalogue reconciliation for failed agents.") if failed and not remaining else None)

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        await engine_checkpoint(run.id, self.code, {"cancelled": True})
        return await self.get_run(run)


async def queue_catalog_refresh(actor: AdministrationContext, agent_ids: list[int]) -> dict[str, Any]:
    assert actor.agent_id is not None
    await actor.require()
    workflow = await ensure_integrated_definition(actor.agent_id, "tool_admin", "catalog_refresh")
    process = await process_service.start_process(agent_id=actor.agent_id, workflow_id=workflow,
        input_data={"agent_ids": agent_ids, "function_name": actor.function_name})
    return {"complete": False, "queued": True, "run_id": str(process.run_id), "status": process.status,
            "agents_selected": len(agent_ids)}
