from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.process.schemas import EngineRunReference, ProcessStartPayload
from bridge.n8n.client import N8NClient
from bridge.n8n.engine import N8NProcessEngine
from bridge.n8n.errors import N8NError, from_http_status
from bridge.n8n.status import normalize_status


def test_status_normalization() -> None:
    assert normalize_status("running") == "running"
    assert normalize_status("waiting") == "waiting"
    assert normalize_status("crashed") == "error"
    assert normalize_status("canceled") == "cancelled"
    assert normalize_status("future-status") == "unknown"


def test_http_error_classification() -> None:
    assert from_http_status(429, "limited").retryable
    assert from_http_status(503, "down").retryable
    assert not from_http_status(401, "bad key").retryable
    assert not from_http_status(404, "missing").retryable


@pytest.mark.asyncio
async def test_sync_exposes_n8n_workflow_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        async def list_workflows(self) -> list[dict[str, Any]]:
            return [
                {"id": "workflow-1", "name": "Same name", "active": True},
                {"id": "workflow-2", "name": "Same name", "active": False},
            ]

    async def fake_client(self: N8NProcessEngine) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(N8NProcessEngine, "_client", fake_client)

    definitions = await N8NProcessEngine().sync_definitions()

    assert [item.engine_process_id for item in definitions] == [
        "workflow-1",
        "workflow-2",
    ]
    assert [item.active for item in definitions] == [True, False]


@pytest.mark.asyncio
async def test_health_only_checks_bridge_configuration_and_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        async def list_workflows(self) -> list[dict[str, Any]]:
            return [{"id": "workflow-1", "name": "Any workflow", "active": True}]

    async def fake_client(self: N8NProcessEngine) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(N8NProcessEngine, "_client", fake_client)
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_API_TOKEN", "api"
    )
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_WEBHOOK_AUTH_TOKEN",
        "webhook",
    )
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_BASE_URL",
        "https://n8n.example",
    )

    health = await N8NProcessEngine().health()

    assert health.status == "healthy"
    assert health.reachable and health.authenticated


@pytest.mark.asyncio
async def test_engine_derives_api_url_from_n8n_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_BASE_URL",
        "https://n8n.example/",
    )
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_API_TOKEN", "key"
    )

    client = await N8NProcessEngine()._client()  # pyright: ignore[reportPrivateUsage]

    assert client.api_base_url == "https://n8n.example/api/v1"


@pytest.mark.asyncio
async def test_client_follows_cursor_pagination_and_api_header() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("cursor") == "next":
            return httpx.Response(200, json={"data": [{"id": "2"}], "nextCursor": None})
        return httpx.Response(200, json={"data": [{"id": "1"}], "nextCursor": "next"})

    client = N8NClient(
        "https://n8n.example/api/v1",
        "key",
        transport=httpx.MockTransport(handler),
    )
    rows = await client.list_workflows(active=True)
    assert [row["id"] for row in rows] == ["1", "2"]
    assert all(request.headers["X-N8N-API-KEY"] == "key" for request in requests)


@pytest.mark.asyncio
async def test_engine_launch_payload_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
            assert workflow_id == "wf-1"
            return {
                "id": "wf-1",
                "name": "Invoice recording",
                "active": True,
                "nodes": [{
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {
                        "path": "invoice",
                        "httpMethod": "POST",
                        "authentication": "headerAuth",
                    },
                    "credentials": {"httpHeaderAuth": {"id": "cred-1", "name": "Webhook"}},
                }],
            }

        async def call_webhook(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
            captured.update(url=url, payload=payload, headers=headers)
            return {"executionId": "123"}

    async def fake_client(self: N8NProcessEngine) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(N8NProcessEngine, "_client", fake_client)
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_WEBHOOK_AUTH_HEADER",
        "X-Webhook-Secret",
    )
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_WEBHOOK_AUTH_TOKEN",
        "secret",
    )
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_WEBHOOK_BASE_URL",
        "https://n8n.example",
    )
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_GALARIS_BASE_URL",
        "https://galaris.example",
    )
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_CALLBACK_AUTH_HEADER",
        "X-Callback-Token",
    )
    run_id = uuid4()
    run = EngineRunReference(
        id=run_id,
        correlation_id="corr-1",
        callback_token="run-secret",
    )
    result = await N8NProcessEngine().start_run(
        "wf-1",
        run,
        ProcessStartPayload(input={"invoice_number": "F-1"}),
    )
    assert result.engine_run_id == "123"
    assert captured["payload"] == {"invoice_number": "F-1"}
    assert captured["headers"]["X-Webhook-Secret"] == "secret"
    assert captured["headers"]["Idempotency-Key"] == "corr-1"
    assert captured["headers"]["X-Callback-Token"] == "run-secret"
    assert captured["headers"]["X-Galaris-Run-Id"] == str(run_id)
    assert captured["headers"]["X-Galaris-Callback-Url"] == (
        f"https://galaris.example/api/processes/runs/{run_id}/events"
    )
    assert captured["url"] == "https://n8n.example/webhook/invoice"


@pytest.mark.asyncio
async def test_engine_rejects_webhook_response_without_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
            assert workflow_id == "wf-1"
            return {
                "id": "wf-1",
                "name": "Invoice recording",
                "active": True,
                "nodes": [{
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {
                        "path": "invoice",
                        "httpMethod": "POST",
                        "authentication": "headerAuth",
                    },
                    "credentials": {"httpHeaderAuth": {"id": "cred-1"}},
                }],
            }

        async def call_webhook(
            self,
            url: str,
            payload: dict[str, Any],
            headers: dict[str, str],
        ) -> dict[str, Any]:
            return {"message": "Workflow was started"}

    async def fake_client(self: N8NProcessEngine) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(N8NProcessEngine, "_client", fake_client)
    monkeypatch.setattr(
        "bridge.n8n.engine.runtime_settings.PROCESS_N8N_WEBHOOK_BASE_URL",
        "https://n8n.example",
    )
    run = EngineRunReference(
        id=uuid4(),
        correlation_id="corr-missing-id",
    )

    with pytest.raises(N8NError) as caught:
        await N8NProcessEngine().start_run(
            "wf-1",
            run,
            ProcessStartPayload(),
        )

    assert caught.value.code == "missing_execution_id"
    assert not caught.value.retryable


@pytest.mark.asyncio
async def test_engine_extracts_last_node_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        async def get_execution(self, execution_id: str) -> dict[str, Any]:
            assert execution_id == "123"
            return {
                "id": "123",
                "status": "success",
                "data": {
                    "resultData": {
                        "lastNodeExecuted": "Formater message",
                        "runData": {
                            "Formater message": [
                                {
                                    "data": {
                                        "main": [
                                            [
                                                {
                                                    "json": {
                                                        "message": "In Example City: 20 °C",
                                                        "weather": {"temperature_c": 20},
                                                    }
                                                }
                                            ]
                                        ]
                                    }
                                }
                            ]
                        },
                    }
                },
            }

    async def fake_client(self: N8NProcessEngine) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(N8NProcessEngine, "_client", fake_client)
    run = EngineRunReference(
        id=uuid4(),
        engine_run_id="123",
        correlation_id="corr-output",
    )

    snapshot = await N8NProcessEngine().get_run(run)

    assert snapshot.status == "success"
    assert snapshot.output == {
        "message": "In Example City: 20 °C",
        "weather": {"temperature_c": 20},
    }


@pytest.mark.asyncio
async def test_engine_extracts_failed_node(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        async def get_execution(self, execution_id: str) -> dict[str, Any]:
            return {
                "id": execution_id,
                "status": "error",
                "data": {
                    "resultData": {
                        "error": {
                            "name": "NodeApiError",
                            "message": "Authorization data is wrong",
                            "node": {"name": "Send to Aster"},
                        }
                    }
                },
            }

    async def fake_client(self: N8NProcessEngine) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(N8NProcessEngine, "_client", fake_client)
    run = EngineRunReference(
        id=uuid4(),
        engine_run_id="failed-1",
        correlation_id="corr-error",
    )

    snapshot = await N8NProcessEngine().get_run(run)

    assert snapshot.status == "error"
    assert snapshot.error is not None
    assert snapshot.error.node_name == "Send to Aster"


@pytest.mark.asyncio
async def test_health_reports_authentication_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        async def list_workflows(self) -> list[dict[str, Any]]:
            raise from_http_status(403, "Authorization data is wrong")

    async def fake_client(self: N8NProcessEngine) -> FakeClient:
        return FakeClient()

    monkeypatch.setattr(N8NProcessEngine, "_client", fake_client)

    health = await N8NProcessEngine().health()

    assert health.status == "error"
    assert health.reachable
    assert not health.authenticated
    assert "unauthorized" in health.details
