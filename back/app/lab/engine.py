"""Integrated Process adapter for costly Lab operations, with atomic result receipts."""

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select

from app.agent import validate_agent_driver
from app.llm import llm_service, model_usages, reasoning_effort_scope, ReasoningEffort
from app.process import (
    EngineError,
    EngineProcessDefinition,
    EngineRunReference,
    EngineRunSnapshot,
    EngineStartResult,
    ProcessEngineHealth,
    ProcessStartPayload,
    ProcessRun,
)
from app.process.interface import engine_checkpoint
from app.tools import McpToolContext
from core.database import get_db

from . import (
    operations,
    mcp_service as service,
    mechanism_evaluation_service as evaluations,
    synthetic_service,
    analysis_service,
    evaluation_service,
)
from .inference_profile import model_binding, validate_binding
from .mcp_access import authorize, fingerprint
from .models import LabOperationResult
from .schemas import (
    EvaluationMechanism,
    MechanismExpectedGenerate,
    EvaluationRunAnalysisRequest,
    TaskAnalysisRequest,
)
from .synthetic_schemas import SyntheticDatasetRequest
from .transactions import atomic_command


class LabEngine:
    code = "lab"
    supports_cancel = True
    cancel_mode = "best_effort"
    start_timeout_seconds = 30.0
    refresh_timeout_seconds = 660.0

    async def health(self) -> ProcessEngineHealth:
        return ProcessEngineHealth(
            tool_code=self.code,
            status="healthy",
            reachable=True,
            authenticated=True,
            supports_cancel=True,
            cancel_mode="best_effort",
            message="Integrated Lab operations",
            checked_at=datetime.now(timezone.utc),
        )

    async def sync_definitions(self) -> list[EngineProcessDefinition]:
        return []

    async def prepare_input(
        self, agent_id: int, workflow_id: str, input_data: dict[str, Any]
    ) -> dict[str, Any]:
        action = TypeAdapter[operations.Operation](operations.Operation).validate_python(
            input_data.get("action")
        )
        mechanism = TypeAdapter[EvaluationMechanism](EvaluationMechanism).validate_python(
            input_data.get("mechanism")
        )
        runtime = validate_agent_driver(input_data.get("runtime"), require_available=False)
        if workflow_id != f"lab:{agent_id}:{action}":
            raise PermissionError("Lab workflow identity does not match the operation and agent.")
        await authorize(
            McpToolContext(agent_id, runtime), action, sources=action == "lab_task_analyze"
        )
        request = dict(input_data.get("request") or {})
        revision_state: dict[str, Any] = {}
        selected_id: int | None = None
        if action == "lab_dataset_generate":
            parsed = SyntheticDatasetRequest.model_validate(request)
            selected_id = parsed.llm_id
            if parsed.source_dataset_id is not None:
                await service.dataset(mechanism, parsed.source_dataset_id, parsed.source_revision)
                revision_state = {
                    "dataset_id": str(parsed.source_dataset_id),
                    "dataset_revision": parsed.source_revision,
                }
            request = parsed.model_dump(mode="json")
        elif action == "lab_expected_generate":
            identifier = UUID(str(request["case_id"]))
            row = await service.case(mechanism, identifier, int(request["revision"]))
            parent = await service.dataset(mechanism, row.dataset_id)
            revision_state = {
                "case_id": str(row.id),
                "case_revision": row.revision,
                "dataset_id": str(parent.id),
                "dataset_revision": parent.revision,
            }
            request["request"] = MechanismExpectedGenerate.model_validate(
                request.get("request")
            ).model_dump(mode="json")
        elif action == "lab_run_analyze":
            row = await service.run(mechanism, UUID(str(request["run_id"])))
            if row.status not in {"completed", "partial", "failed", "cancelled"}:
                raise ValueError("Wait for a terminal benchmark before analysis.")
            revision_state = {
                "run_id": str(row.id),
                "run_state": service.dump(evaluations.EvaluationRunRead.model_validate(row)),
                "run_fingerprint": fingerprint(
                    service.dump(evaluations.EvaluationRunRead.model_validate(row))
                ),
            }
            request["request"] = EvaluationRunAnalysisRequest.model_validate(
                request.get("request")
            ).model_dump(mode="json")
        else:
            task = await evaluation_service.get_task(UUID(str(request["task_id"])))
            if task is None or not await evaluation_service.is_registered(task.id):
                raise LookupError("Register an existing Task in the Lab before diagnosis.")
            revision_state = {"task_id": str(task.id), "task_revision": task.revision}
            request["request"] = TaskAnalysisRequest.model_validate(
                request.get("request")
            ).model_dump(mode="json")
        llm = (
            await llm_service.get_llm(selected_id)
            if selected_id is not None
            else await llm_service.get_profile_llm_for_agent_id(model_usages.LAB, agent_id)
        )
        if llm is None or "chat" not in llm.service_capabilities:
            raise ValueError(
                "Configure an available Lab chat model before starting this operation."
            )
        if action == "lab_dataset_generate":
            request["llm_id"] = llm.id
        return {
            "action": action,
            "mechanism": mechanism,
            "request": request,
            "runtime": runtime,
            "llm_id": llm.id,
            "binding": model_binding(llm),
            "revisions": revision_state,
            "reasoning_effort": await llm_service.get_profile_reasoning_effort_for_agent_id(
                model_usages.LAB, agent_id
            ),
            "request_fingerprint": input_data.get("request_fingerprint"),
        }

    async def start_run(
        self, engine_process_id: str, run: EngineRunReference, payload: ProcessStartPayload
    ) -> EngineStartResult:
        return EngineStartResult(accepted=True, engine_run_id=str(run.id))

    async def _check_revisions(self, frozen: dict[str, Any]) -> None:
        revisions = frozen["revisions"]
        mechanism = cast(EvaluationMechanism, frozen["mechanism"])
        if revisions.get("case_id"):
            await service.case(mechanism, UUID(revisions["case_id"]), revisions["case_revision"])
        if revisions.get("dataset_id"):
            await service.dataset(
                mechanism, UUID(revisions["dataset_id"]), revisions["dataset_revision"]
            )
        if revisions.get("task_id"):
            row = await evaluation_service.get_task(UUID(revisions["task_id"]))
            if row is None or row.revision != revisions["task_revision"]:
                raise ValueError("Task changed after admission; submit a new diagnosis.")
        if revisions.get("run_id"):
            row = await service.run(mechanism, UUID(revisions["run_id"]))
            if (
                fingerprint(service.dump(evaluations.EvaluationRunRead.model_validate(row)))
                != revisions["run_fingerprint"]
            ):
                raise ValueError("Benchmark changed after admission; submit a new analysis.")

    async def _execute(self, frozen: dict[str, Any]) -> dict[str, Any]:
        mechanism = cast(EvaluationMechanism, frozen["mechanism"])
        request = frozen["request"]
        llm_id = int(frozen["llm_id"])
        if frozen["action"] == "lab_dataset_generate":
            return service.dump(
                await synthetic_service.generate_dataset(
                    mechanism, SyntheticDatasetRequest.model_validate(request)
                )
            )
        if frozen["action"] == "lab_expected_generate":
            return service.dump(
                await evaluations.generate_expected(
                    mechanism,
                    UUID(request["case_id"]),
                    MechanismExpectedGenerate.model_validate(request["request"]),
                    llm_id=llm_id,
                )
            )
        if frozen["action"] == "lab_run_analyze":
            result = await evaluations.analyze_run(
                mechanism,
                UUID(request["run_id"]),
                EvaluationRunAnalysisRequest.model_validate(request["request"]),
                llm_id=llm_id,
                expected_state=frozen["revisions"]["run_state"],
            )
            return result.model_dump(mode="json", exclude={"results", "campaigns"})
        task_request = TaskAnalysisRequest.model_validate(request["request"])
        return service.dump(
            await analysis_service.analyze_task(
                task_id=UUID(request["task_id"]),
                language=task_request.language,
                user_context=task_request.user_context,
                llm_id=llm_id,
                reasoning_effort=cast(ReasoningEffort | None, frozen.get("reasoning_effort")),
            )
        )

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        data = await engine_checkpoint(run.id, self.code)
        saved = await get_db().scalar(
            select(LabOperationResult).where(LabOperationResult.process_run_id == run.id)
        )
        if saved is not None:
            return EngineRunSnapshot(
                status="success", output={"result_id": str(saved.id), "operation_id": str(run.id)}
            )
        metadata = data["metadata"]
        if metadata.get("failure"):
            return EngineRunSnapshot(
                status="error",
                error=EngineError(code="lab_operation_failed", message=metadata["failure"]),
            )
        deadline = (
            datetime.fromisoformat(metadata["deadline"]) if metadata.get("deadline") else None
        )
        active = deadline is not None and deadline > datetime.now(timezone.utc)
        if metadata.get("cancel_requested"):
            return EngineRunSnapshot(status="cancelling" if active else "cancelled")
        if data["terminal"]:
            return EngineRunSnapshot(status="cancelled")
        if metadata.get("execution"):
            return EngineRunSnapshot(
                status="running" if active else "unknown",
                error=None
                if active
                else EngineError(
                    code="lab_execution_uncertain",
                    message="Worker interrupted; no automatic repeat of a potentially billed inference. Inspect before starting a new operation.",
                ),
            )
        frozen = data["input"]
        ctx = McpToolContext(
            int(data["agent_id"]),
            validate_agent_driver(frozen["runtime"], require_available=False),
            data.get("task_id"),
        )
        claimed = await engine_checkpoint(
            run.id,
            self.code,
            {
                "deadline": (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=self.refresh_timeout_seconds + 30)
                ).isoformat()
            },
            claim="execution",
            preserve_if={"execution": "started", "cancel_requested": True},
        )
        if not claimed["claimed"]:
            return EngineRunSnapshot(
                status="cancelled" if claimed["metadata"].get("cancel_requested") else "running"
            )
        try:
            await authorize(ctx, frozen["action"], sources=frozen["action"] == "lab_task_analyze")
            llm = await llm_service.get_llm(int(frozen["llm_id"]))
            if llm is None:
                raise ValueError("The admitted model was removed.")
            validate_binding(llm, frozen)
            await self._check_revisions(frozen)
            await get_db().commit()
            with atomic_command():
                with reasoning_effort_scope(
                    cast(ReasoningEffort | None, frozen.get("reasoning_effort"))
                ):
                    payload = await self._execute(frozen)
                # Serialize final publication against cancellation, then recheck the live grant.
                current = await get_db().scalar(
                    select(ProcessRun)
                    .where(ProcessRun.id == run.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    current is None
                    or current.status in {"cancelled", "cancelling", "error", "success"}
                    or current.engine_metadata.get("cancel_requested")
                ):
                    await get_db().rollback()
                    await engine_checkpoint(
                        run.id,
                        self.code,
                        {
                            "deadline": datetime.now(timezone.utc).isoformat(),
                            "cancel_requested": True,
                        },
                    )
                    return EngineRunSnapshot(status="cancelled")
                await authorize(
                    ctx, frozen["action"], sources=frozen["action"] == "lab_task_analyze"
                )
                if frozen["action"] != "lab_run_analyze":
                    await self._check_revisions(frozen)
                saved = LabOperationResult(process_run_id=run.id, payload=payload)
                get_db().add(saved)
                await get_db().flush()
                identifier = saved.id
            await get_db().commit()
            return EngineRunSnapshot(
                status="success", output={"result_id": str(identifier), "operation_id": str(run.id)}
            )
        except Exception as exc:
            await get_db().rollback()
            # Store a bounded diagnostic, without serializing arbitrary provider payloads or credentials.
            message = f"Lab operation failed ({type(exc).__name__}); inspect the correlated inference or start a corrected operation."
            await engine_checkpoint(
                run.id,
                self.code,
                {"failure": message, "deadline": datetime.now(timezone.utc).isoformat()},
            )
            return EngineRunSnapshot(
                status="error", error=EngineError(code="lab_operation_failed", message=message)
            )

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        await engine_checkpoint(run.id, self.code, {"cancel_requested": True})
        return await self.get_run(run)
