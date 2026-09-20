from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent.contracts import WorkingSet
from app.tools.mcp_loader import McpToolContext
from app.tools.resource_effects import record_tool_resources


@pytest.mark.asyncio
async def test_multimedia_process_promotes_only_completed_canonical_outputs(monkeypatch):
    from app.tools import resource_effects
    recorded = AsyncMock()
    monkeypatch.setattr(resource_effects.task_port, "upsert_working_resource", recorded)
    ctx = McpToolContext(agent_id=1, runtime="internal", task_id=uuid4())
    payload = {"id": str(uuid4()), "tool_code": "multimedia", "status": "running",
               "output": {"files": [{"uri": "console:///tmp/music.wav", "media_type": "audio/wav"}]}}
    await record_tool_resources(ctx, "process_get_run", {}, payload)
    recorded.assert_not_awaited()
    payload["status"] = "success"
    await record_tool_resources(ctx, "process_get_run", {}, payload)
    assert recorded.await_args.args[1].reference == "console://tmp/music.wav"


@pytest.mark.asyncio
async def test_document_result_records_exact_role_and_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import resource_effects

    task_id = uuid4()
    document_id = uuid4()
    recorded = AsyncMock()
    monkeypatch.setattr(
        resource_effects.task_port,
        "get_working_set",
        AsyncMock(return_value=WorkingSet()),
    )
    monkeypatch.setattr(
        resource_effects.task_port,
        "upsert_working_resource",
        recorded,
    )

    await record_tool_resources(
        McpToolContext(agent_id=1, runtime="internal", task_id=task_id),
        "file_create",
        {"path": "document://", "name": "Draft"},
        (
            '{"uri":"document://%s","revision":1,'
            '"operation":"create","state":"created"}' % document_id
        ),
    )

    resource = recorded.await_args.args[1]
    assert resource.role == "primary_working_document"
    assert resource.reference == f"document://{document_id}"
    assert resource.revision == 1


@pytest.mark.asyncio
async def test_file_delivery_records_artifact_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import resource_effects

    recorded = AsyncMock()
    monkeypatch.setattr(
        resource_effects.task_port,
        "upsert_working_resource",
        recorded,
    )
    context = McpToolContext(
        agent_id=1,
        runtime="internal",
        task_id=uuid4(),
    )

    await record_tool_resources(
        context,
        "messenger_room_send_file",
        {"room_id": "room-1", "filename": "console://final/report.html"},
        "File sent",
    )

    resources = [call.args[1] for call in recorded.await_args_list]
    assert [resource.resource_type for resource in resources] == [
        "artifact",
        "artifact",
        "delivery_receipt",
    ]
    assert resources[0].state == "active"
    assert resources[0].metadata["delivered_copy"] is True
    assert "removed_after_delivery" not in resources[0].metadata
    assert resources[1].role == "final_artifact"
    assert resources[2].metadata["destination"] == "room-1"


@pytest.mark.asyncio
async def test_audio_delivery_records_artifact_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import resource_effects

    task_id = uuid4()
    recorded = AsyncMock()
    monkeypatch.setattr(
        resource_effects.task_port,
        "upsert_working_resource",
        recorded,
    )

    await record_tool_resources(
        McpToolContext(agent_id=1, runtime="internal", task_id=task_id),
        "messenger_send_audio_message",
        {"user": "Nicolas", "message": "Salut"},
        {
            "destination": "latest-room",
            "connection_id": 19,
            "provider": "ElevenLabs",
            "size": 9,
        },
    )

    resources = [call.args[1] for call in recorded.await_args_list]
    assert [resource.resource_type for resource in resources] == [
        "artifact",
        "delivery_receipt",
    ]
    assert all(resource.producer_task_id == task_id for resource in resources)
    assert resources[0].role == "final_artifact"
    assert resources[0].metadata["delivered"] is True
    assert resources[1].metadata["destination"] == "latest-room"


@pytest.mark.asyncio
async def test_cross_provider_delivery_records_exact_source_and_destination_uris(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import resource_effects

    recorded = AsyncMock()
    monkeypatch.setattr(
        resource_effects.task_port,
        "upsert_working_resource",
        recorded,
    )

    await record_tool_resources(
        McpToolContext(agent_id=1, runtime="internal", task_id=uuid4()),
        "messenger_room_send_file",
        {"room_id": "room-1", "filename": "console://reports/report.pdf"},
        {
            "source_uri": "console://reports/report.pdf",
            "uri": "nextcloud://provider-room/attachment-12",
            "name": "original-report.pdf",
            "size": 12,
        },
    )

    resources = [call.args[1] for call in recorded.await_args_list]
    assert resources[0].resource_type == "artifact"
    assert resources[0].reference == "console://reports/report.pdf"
    assert resources[1].reference == "nextcloud://provider-room/attachment-12"
    assert resources[1].metadata["source"] == "console://reports/report.pdf"
    assert resources[2].metadata["filename"] == "console://reports/report.pdf"
    assert resources[2].metadata["uri"] == "nextcloud://provider-room/attachment-12"


@pytest.mark.asyncio
async def test_complete_binary_write_records_a_produced_console_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import resource_effects

    recorded = AsyncMock()
    monkeypatch.setattr(
        resource_effects.task_port,
        "upsert_working_resource",
        recorded,
    )

    await record_tool_resources(
        McpToolContext(agent_id=1, runtime="internal", task_id=uuid4()),
        "file_write",
        {
            "uri": "console://artifacts/payload.bin",
            "content": "AP8Q",
            "encoding": "base64",
        },
        (
            '{"uri":"console://artifacts/payload.bin","operation":"write",'
            '"state":"written","size":3}'
        ),
    )

    resource = recorded.await_args.args[1]
    assert resource.reference == "console://artifacts/payload.bin"
    assert resource.resource_type == "artifact"
    assert resource.metadata["produced"] is True
    assert "content" not in resource.metadata


@pytest.mark.asyncio
async def test_file_upload_records_remote_artifact_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import resource_effects

    recorded = AsyncMock()
    monkeypatch.setattr(
        resource_effects.task_port,
        "upsert_working_resource",
        recorded,
    )

    await record_tool_resources(
        McpToolContext(agent_id=1, runtime="internal", task_id=uuid4()),
        "file_upload",
        {
            "tool_code": "nextcloud",
            "source": "console://final/report.html",
            "destination": "Shared/report.html",
        },
        "Upload completed",
    )

    resources = [call.args[1] for call in recorded.await_args_list]
    assert [resource.resource_type for resource in resources] == [
        "artifact",
        "delivery_receipt",
    ]
    assert resources[0].reference == "nextcloud://Shared/report.html"
    assert resources[1].metadata["source"] == "console://final/report.html"


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [
    "ps -eo pid,args | grep -E 'pytest|git push' | head -30",
    "printf 'git push succeeded'",
    "git push origin main; true",
    "git add -A && git commit -m publish && git push origin main",
])
async def test_shell_success_is_not_a_verified_git_delivery(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    from app.tools import resource_effects

    recorded = AsyncMock()
    monkeypatch.setattr(
        resource_effects.task_port,
        "upsert_working_resource",
        recorded,
    )

    await record_tool_resources(
        McpToolContext(agent_id=1, runtime="internal", task_id=uuid4()),
        "console_exec",
        {
            "command": command,
            "cwd": "work/www-lecluse-net",
        },
        {"status": "completed", "exit_code": 0},
    )

    recorded.assert_not_awaited()


@pytest.mark.asyncio
async def test_console_command_without_push_records_no_delivery_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import resource_effects

    recorded = AsyncMock()
    monkeypatch.setattr(
        resource_effects.task_port,
        "upsert_working_resource",
        recorded,
    )

    await record_tool_resources(
        McpToolContext(agent_id=1, runtime="internal", task_id=uuid4()),
        "console_exec",
        {"command": "npm run build", "cwd": "work/www-lecluse-net"},
        {"status": "completed", "exit_code": 0},
    )

    recorded.assert_not_awaited()
