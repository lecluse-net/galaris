from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.process import mcp
from app.tools.mcp_loader import McpToolContext


@asynccontextmanager
async def _db_session() -> AsyncIterator[None]:
    yield


@pytest.mark.asyncio
async def test_process_list_is_scoped_to_calling_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_for_agent = AsyncMock(return_value=[{"workflow_id": "assigned"}])
    monkeypatch.setattr(mcp.process_service, "list_for_agent", list_for_agent)

    result = await mcp.process_list(McpToolContext(agent_id=42, runtime="hermes"))

    assert result == [{"workflow_id": "assigned"}]
    list_for_agent.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_process_get_refuses_workflow_not_assigned_to_calling_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_for_agent = AsyncMock(return_value=None)
    monkeypatch.setattr(mcp.process_service, "get_for_agent", get_for_agent)
    monkeypatch.setattr(mcp, "context_language", AsyncMock(return_value="en"))

    with pytest.raises(PermissionError):
        await mcp.process_get(
            McpToolContext(agent_id=42, runtime="internal"),
            "not-assigned",
        )

    get_for_agent.assert_awaited_once_with(42, "not-assigned")


@pytest.mark.asyncio
async def test_process_start_forwards_calling_agent_and_task_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def model_dump(self, *, mode: str) -> dict[str, str]:
            assert mode == "json"
            return {"run_id": "run-1", "status": "queued"}

    response = Response()
    start_process = AsyncMock(return_value=response)
    monkeypatch.setattr(mcp.process_service, "start_process", start_process)
    task_id = uuid4()

    result = await mcp.process_start(
        McpToolContext(agent_id=42, runtime="hermes", task_id=task_id),
        "assigned",
        input={"invoice_id": "INV-1"},
        files=[
            {
                "uri": "nextcloud://Invoices/INV-1.pdf",
                "description": "Original invoice",
            }
        ],
    )

    assert result == {"run_id": "run-1", "status": "queued"}
    start_process.assert_awaited_once_with(
        agent_id=42,
        workflow_id="assigned",
        input_data={"invoice_id": "INV-1"},
        files=[
            mcp.ProcessFileInput(
                uri="nextcloud://Invoices/INV-1.pdf",
                description="Original invoice",
            )
        ],
        wait_for_completion=False,
        idempotency_key=None,
        task_id=task_id,
        runtime="hermes",
    )


@pytest.mark.asyncio
async def test_process_admin_can_create_update_and_delete_for_another_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import database as database_module

    now = datetime.now(timezone.utc)
    tool = SimpleNamespace(id=5, code="n8n")
    definition = SimpleNamespace(
        id=8,
        agent_id=77,
        tool_id=tool.id,
        engine_process_id="invoice-workflow",
        label="Record invoice",
        description="Initial",
        created_at=now,
        updated_at=None,
    )
    create_definition = AsyncMock(return_value=definition)
    update_definition = AsyncMock(return_value=definition)
    delete_definition = AsyncMock(return_value=True)
    monkeypatch.setattr(database_module, "get_db_session", _db_session)
    monkeypatch.setattr(
        mcp.process_service,
        "get_process_tool_by_code",
        AsyncMock(return_value=tool),
    )
    monkeypatch.setattr(mcp.process_service, "create_definition", create_definition)
    monkeypatch.setattr(mcp.process_service, "update_definition", update_definition)
    monkeypatch.setattr(mcp.process_service, "delete_definition", delete_definition)
    monkeypatch.setattr(
        mcp.process_service,
        "list_process_tools",
        AsyncMock(return_value=[tool]),
    )
    ctx = McpToolContext(agent_id=1, runtime="internal")

    created = await mcp.process_admin_create(
        ctx,
        agent_id=77,
        workflow_id="invoice-workflow",
        label="Record invoice",
        description="Initial",
    )
    updated = await mcp.process_admin_update(
        ctx,
        process_id=8,
        agent_id=77,
        label="Updated invoice",
        clear_description=True,
    )
    deleted = await mcp.process_admin_delete(ctx, process_id=8)

    create_data = create_definition.await_args.args[0]
    assert create_data.agent_id == 77
    assert create_data.tool_id == tool.id
    assert create_data.engine_process_id == "invoice-workflow"
    update_data = update_definition.await_args.args[1]
    assert update_data.model_dump(exclude_unset=True) == {
        "agent_id": 77,
        "label": "Updated invoice",
        "description": None,
    }
    assert created["agent_id"] == 77
    assert created["tool_code"] == "n8n"
    assert updated["agent_id"] == 77
    assert deleted == {"process_id": 8, "deleted": True}
    delete_definition.assert_awaited_once_with(8)


@pytest.mark.asyncio
async def test_process_admin_can_inspect_another_agents_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import database as database_module

    run_id = uuid4()

    class Detail:
        launcher_agent_id = 77

        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {
                "id": str(run_id),
                "launcher_agent_id": self.launcher_agent_id,
            }

    get_run_detail = AsyncMock(return_value=Detail())
    monkeypatch.setattr(database_module, "get_db_session", _db_session)
    monkeypatch.setattr(mcp.process_service, "get_run_detail", get_run_detail)

    result = await mcp.process_admin_get_run(
        McpToolContext(agent_id=1, runtime="internal"),
        str(run_id),
    )

    assert result["launcher_agent_id"] == 77
    get_run_detail.assert_awaited_once_with(run_id, refresh_if_stale=True)
