"""n8n implementation of the ProcessEngine protocol."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, cast

from core import settings
from core.params import runtime_settings
from core.i18n import render_prompt, t
from app.process import (
    EngineError,
    EngineProcessDefinition,
    EngineRunReference,
    EngineRunSnapshot,
    EngineStartResult,
    ProcessStartPayload,
    ProcessEngineHealth,
)

from .client import N8NClient
from .errors import N8NError
from .schemas import N8NExecution, N8NWorkflow
from .status import normalize_status


class N8NProcessEngine:
    code = "n8n"
    supports_cancel = True
    cancel_mode = "best_effort"

    async def _client(self) -> N8NClient:
        base = runtime_settings.PROCESS_N8N_BASE_URL.rstrip("/")
        if not base:
            raise N8NError("not_configured", t("process.n8n.api_url_missing"))
        return N8NClient(
            f"{base}/api/v1",
            runtime_settings.PROCESS_N8N_API_TOKEN,
            timeout=runtime_settings.PROCESS_START_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _webhook_path(workflow: N8NWorkflow) -> str | None:
        for node in workflow.nodes:
            if str(node.get("type") or "").endswith(".webhook"):
                raw_parameters = node.get("parameters")
                parameters = cast(dict[str, Any], raw_parameters) if isinstance(raw_parameters, dict) else {}
                path = str(parameters.get("path") or "").strip("/")
                return path or None
        return None

    async def sync_definitions(self) -> list[EngineProcessDefinition]:
        client = await self._client()
        return [
            EngineProcessDefinition(
                engine_process_id=workflow.id,
                label=workflow.name,
                active=workflow.active,
            )
            for workflow in (
                N8NWorkflow.model_validate(raw)
                for raw in await client.list_workflows()
            )
        ]

    async def health(self) -> ProcessEngineHealth:
        try:
            workflows = await (await self._client()).list_workflows()
        except N8NError as exc:
            return ProcessEngineHealth(
                tool_code=self.code,
                status="error",
                reachable=exc.code != "engine_unreachable",
                authenticated=exc.code != "unauthorized",
                supports_cancel=self.supports_cancel,
                cancel_mode="best_effort",
                message=exc.message,
                details=[exc.code],
                checked_at=datetime.now(timezone.utc),
            )
        return ProcessEngineHealth(
            tool_code=self.code,
            status="healthy",
            reachable=True,
            authenticated=True,
            supports_cancel=self.supports_cancel,
            cancel_mode="best_effort",
            message=render_prompt(
                t("process.n8n.api_available"), count=len(workflows)
            ),
            details=[],
            checked_at=datetime.now(timezone.utc),
        )

    async def start_run(
        self,
        engine_process_id: str,
        run: EngineRunReference,
        payload: ProcessStartPayload,
    ) -> EngineStartResult:
        workflow = N8NWorkflow.model_validate(
            await (await self._client()).get_workflow(engine_process_id)
        )
        path = self._webhook_path(workflow)
        webhook_base = (
            runtime_settings.PROCESS_N8N_WEBHOOK_BASE_URL
            or runtime_settings.PROCESS_N8N_BASE_URL
        ).rstrip("/")
        webhook_url = f"{webhook_base}/webhook/{path}" if webhook_base and path else ""
        if not webhook_url:
            raise N8NError(
                "invalid_webhook_url",
                t("process.n8n.workflow_webhook_missing"),
            )
        auth_header = runtime_settings.PROCESS_N8N_WEBHOOK_AUTH_HEADER
        auth_token = runtime_settings.PROCESS_N8N_WEBHOOK_AUTH_TOKEN
        headers = {
            "Content-Type": "application/json",
            # Outbox delivery is at least once. This stable token lets the
            # workflow deduplicate a second call after an ambiguous timeout,
            # before executing business side effects.
            "Idempotency-Key": run.correlation_id,
        }
        if auth_token:
            headers[auth_header] = auth_token
        callback_base = (
            runtime_settings.PROCESS_GALARIS_BASE_URL or settings.APP_HOST
        ).rstrip("/")
        callback_header = runtime_settings.PROCESS_N8N_CALLBACK_AUTH_HEADER.strip()
        if run.callback_token and callback_header:
            headers[callback_header] = run.callback_token
        if callback_base:
            headers["X-Galaris-Run-Id"] = str(run.id)
            headers["X-Galaris-Callback-Url"] = (
                f"{callback_base}/api/processes/runs/{run.id}/events"
            )
        body = dict(payload.input)
        if payload.files:
            body["files"] = [
                item.model_dump(mode="json", exclude={"uri", "runtime", "task_id"})
                for item in payload.files
            ]
        response = await (await self._client()).call_webhook(webhook_url, body, headers)
        engine_run_id: Optional[str] = None
        for key in ("executionId", "execution_id", "id"):
            value = response.get(key)
            if value is not None and str(value).strip():
                engine_run_id = str(value).strip()
                break
        if engine_run_id is None:
            raise N8NError(
                "missing_execution_id",
                t("process.n8n.webhook_execution_id_missing"),
                retryable=False,
            )
        return EngineStartResult(accepted=True, engine_run_id=engine_run_id, raw=response)

    async def get_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        if not run.engine_run_id:
            return EngineRunSnapshot(status="unknown")
        raw = await (await self._client()).get_execution(run.engine_run_id)
        execution = N8NExecution.model_validate(raw)
        status = normalize_status(execution.status)
        raw_data = raw.get("data")
        data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
        raw_result = data.get("resultData")
        result_data = cast(dict[str, Any], raw_result) if isinstance(raw_result, dict) else {}
        error: EngineError | None = None
        if status == "error":
            execution_error = result_data.get("error")
            if isinstance(execution_error, dict):
                typed_error = cast(dict[str, Any], execution_error)
                raw_node = typed_error.get("node")
                node = cast(dict[str, Any], raw_node) if isinstance(raw_node, dict) else {}
                error = EngineError(
                    code=str(typed_error.get("name") or "n8n_execution_error"),
                    message=str(
                        typed_error.get("message")
                        or t("process.n8n.execution_error")
                    ),
                    node_name=str(node.get("name")) if node.get("name") else None,
                )
        return EngineRunSnapshot(
            status=cast(Any, status),
            engine_run_id=execution.id,
            output=self._execution_output(result_data) if status == "success" else None,
            error=error,
            raw=raw,
        )

    @staticmethod
    def _execution_output(result_data: dict[str, Any]) -> dict[str, Any] | None:
        """Return the first JSON item produced by the last executed node."""
        last_node = result_data.get("lastNodeExecuted")
        run_data = result_data.get("runData")
        if not isinstance(last_node, str) or not isinstance(run_data, dict):
            return None
        typed_run_data = cast(dict[str, Any], run_data)
        raw_node_runs = typed_run_data.get(last_node)
        if not isinstance(raw_node_runs, list) or not raw_node_runs:
            return None
        node_runs = cast(list[Any], raw_node_runs)
        raw_last_run = node_runs[-1]
        if not isinstance(raw_last_run, dict):
            return None
        last_run = cast(dict[str, Any], raw_last_run)
        execution_data = last_run.get("data")
        if not isinstance(execution_data, dict):
            return None
        typed_execution_data = cast(dict[str, Any], execution_data)
        raw_main_outputs = typed_execution_data.get("main")
        if not isinstance(raw_main_outputs, list):
            return None
        main_outputs = cast(list[Any], raw_main_outputs)
        for raw_branch in main_outputs:
            if not isinstance(raw_branch, list):
                continue
            branch = cast(list[Any], raw_branch)
            for raw_item in branch:
                if not isinstance(raw_item, dict):
                    continue
                item = cast(dict[str, Any], raw_item)
                value = item.get("json")
                if isinstance(value, dict):
                    typed_value = cast(dict[Any, Any], value)
                    return {str(key): child for key, child in typed_value.items()}
        return None

    async def cancel_run(self, run: EngineRunReference) -> EngineRunSnapshot:
        if not run.engine_run_id:
            raise N8NError(
                "cancel_unsupported", t("process.n8n.execution_id_unknown")
            )
        raw = await (await self._client()).stop_execution(run.engine_run_id)
        status = normalize_status(raw.get("status") or "cancelled")
        return EngineRunSnapshot(
            status=cast(Any, status if status != "unknown" else "cancelled"),
            engine_run_id=run.engine_run_id,
            raw=raw,
        )
