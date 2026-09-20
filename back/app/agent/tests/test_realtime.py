from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import realtime as realtime_service
from app.agent.contracts import AgentRunContext, TaskPhase
from app.agent.task_port import TaskAmendmentUnavailableError


@pytest.mark.asyncio
@pytest.mark.parametrize("during_write", [False, True])
async def test_realtime_revision_conflict_never_creates_a_replacement(monkeypatch, during_write):
    from app.agent.task_port import TaskAmendmentRevisionConflict

    task_id = uuid4()
    target = SimpleNamespace(id=task_id, agent_id=7, parent_id=None,
        message_group_id="room-voice", data={}, status=TaskPhase.EXEC,
        revision=4 if during_write else 5)
    monkeypatch.setattr(realtime_service.task_port, "get_by_id", AsyncMock(return_value=target))
    monkeypatch.setattr(realtime_service.task_port, "operational_state", AsyncMock(return_value={
        "operational_state": "RUNNING", "amendable": True,
    }))
    monkeypatch.setattr(realtime_service.task_port, "amend", AsyncMock(side_effect=TaskAmendmentRevisionConflict("changed")))
    create = AsyncMock()
    monkeypatch.setattr(realtime_service.task_port, "create", create)
    result = await realtime_service.submit_realtime_task(agent_id=7,
        objective="Ajouter le PDF.", label="Report", conversation_id="room-voice",
        transport_kind="nextcloud_talk", language="fr", disposition="AMEND_CURRENT",
        target_task_id=task_id, expected_revision=4)
    assert result["created"] is False and result["amended"] is False
    assert result["conflict"] == "amendment_revision_changed"
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_realtime_task_submission_uses_durable_task_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    drafts: list[object] = []
    scheduled: list[tuple[object, bool]] = []

    async def create(draft: object) -> object:
        drafts.append(draft)
        return SimpleNamespace(id=task_id, status=TaskPhase.CREATE, revision=1)

    monkeypatch.setattr(realtime_service.task_port, "create", create)
    monkeypatch.setattr(
        realtime_service.task_port,
        "schedule",
        lambda identifier, *, fast=False: scheduled.append((identifier, fast)),
    )
    monkeypatch.setattr(
        realtime_service.task_port,
        "operational_state",
        AsyncMock(return_value={"operational_state": "QUEUED"}),
    )

    result = await realtime_service.submit_realtime_task(
        agent_id=7,
        objective="Prépare le compte rendu de la réunion.",
        label="Compte rendu",
        conversation_id="room-voice",
        transport_kind="nextcloud_talk",
        language="fr",
    )

    assert result["task_id"] == f"galaris://task/{task_id}"
    assert result["task_uri"] == f"galaris://task/{task_id}"
    assert result["created"] is True
    assert scheduled == [(task_id, True)]
    draft = drafts[0]
    assert getattr(draft, "agent_id") == 7
    assert getattr(draft, "requester_agent_id") == 7
    assert getattr(draft, "ai") is True
    assert getattr(draft, "data")["origin"] == "realtime_voice"


@pytest.mark.asyncio
async def test_realtime_task_submission_can_amend_current_deliverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    target = SimpleNamespace(
        id=task_id,
        agent_id=7,
        parent_id=None,
        message_group_id="room-voice",
        data={"conversation_id": "room-voice"},
        status=TaskPhase.EXEC,
        revision=4,
    )
    amend = AsyncMock(
        return_value=SimpleNamespace(
            id=task_id,
            status=TaskPhase.CREATE,
            revision=5,
        )
    )
    monkeypatch.setattr(
        realtime_service.task_port,
        "get_by_id",
        AsyncMock(return_value=target),
    )
    monkeypatch.setattr(realtime_service.task_port, "amend", amend)
    monkeypatch.setattr(
        realtime_service.task_port,
        "operational_state",
        AsyncMock(
            side_effect=[
                {"operational_state": "RUNNING", "amendable": True},
                {"operational_state": "QUEUED"},
            ]
        ),
    )

    result = await realtime_service.submit_realtime_task(
        agent_id=7,
        objective="Ajoute aussi une version PDF.",
        label="Compte rendu",
        conversation_id="room-voice",
        transport_kind="nextcloud_talk",
        language="fr",
        disposition="AMEND_CURRENT",
        target_task_id=task_id,
        expected_revision=4,
        reason="Même livrable.",
    )

    assert result["created"] is False
    assert result["amended"] is True
    assert result["task_id"] == f"galaris://task/{task_id}"
    assert result["task_uri"] == f"galaris://task/{task_id}"
    amend.assert_awaited_once()
    call = amend.await_args.kwargs
    assert call["task_id"] == task_id
    assert call["expected_revision"] == 4
    assert call["disposition"] == "AMEND_CURRENT"


@pytest.mark.asyncio
async def test_realtime_unavailable_amendment_requires_explicit_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_id = uuid4()
    created_id = uuid4()
    target = SimpleNamespace(
        id=target_id,
        agent_id=7,
        parent_id=None,
        message_group_id="room-voice",
        data={"conversation_id": "room-voice"},
        status=TaskPhase.EXEC,
        revision=4,
    )
    created = SimpleNamespace(id=created_id, status=TaskPhase.CREATE, revision=1)
    monkeypatch.setattr(
        realtime_service.task_port,
        "get_by_id",
        AsyncMock(return_value=target),
    )
    monkeypatch.setattr(
        realtime_service.task_port,
        "operational_state",
        AsyncMock(
            side_effect=[
                {"operational_state": "RUNNING", "amendable": True},
                {"operational_state": "QUEUED"},
            ]
        ),
    )
    monkeypatch.setattr(
        realtime_service.task_port,
        "amend",
        AsyncMock(side_effect=TaskAmendmentUnavailableError("plan materialized")),
    )
    create = AsyncMock(return_value=created)
    monkeypatch.setattr(realtime_service.task_port, "create", create)
    scheduled: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        realtime_service.task_port,
        "schedule",
        lambda identifier, *, fast=False: scheduled.append((identifier, fast)),
    )

    result = await realtime_service.submit_realtime_task(
        agent_id=7,
        objective="Prépare un autre livrable.",
        label="Livrable séparé",
        conversation_id="room-voice",
        transport_kind="nextcloud_talk",
        language="fr",
        disposition="AMEND_CURRENT",
        target_task_id=target_id,
        expected_revision=4,
    )

    assert result["created"] is False
    assert result["action"] == "CONFLICT"
    assert result["requested_action"] == "AMEND_CURRENT"
    assert result["conflict"] == "amendment_no_longer_safe"
    create.assert_not_awaited()
    assert scheduled == []

    result = await realtime_service.submit_realtime_task(
        agent_id=7, objective="Prépare un autre livrable.", label="Livrable séparé",
        conversation_id="room-voice", transport_kind="nextcloud_talk", language="fr",
        disposition="CREATE_NEW",
    )
    assert result["created"] is True
    assert result["operational_state"] == "QUEUED"
    assert scheduled == [(created_id, True)]
    draft = create.await_args.args[0]
    assert "admission_fallback" not in getattr(draft, "data")


@pytest.mark.asyncio
async def test_realtime_task_status_is_scoped_to_the_current_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()

    async def get_by_id(_task_id: object) -> object:
        return SimpleNamespace(
            id=task_id,
            agent_id=8,
            label="Private task",
            status="SUCCESS",
            paused=False,
        )

    monkeypatch.setattr(realtime_service.task_port, "get_by_id", get_by_id)

    result = await realtime_service.realtime_task_status(task_id, agent_id=7)

    assert result == {
        "found": False,
        "task_id": f"galaris://task/{task_id}",
        "task_uri": f"galaris://task/{task_id}",
    }


@pytest.mark.asyncio
async def test_realtime_voice_context_uses_conversation_action_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent import agent_service, context, executor_service
    from app import process
    from core.params import params_service

    monkeypatch.setattr(
        agent_service,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                id=7,
                code="alice",
                first_name="Alice",
                last_name="Martin",
                agent_driver="hermes",
                title=SimpleNamespace(gender="F"),
                personality="concise",
                job_description="help",
                job_title="Assistant",
            )
        ),
    )
    contact_id = uuid4()
    document_id = uuid4()
    context_builder = AsyncMock(
        return_value=AgentRunContext(
            shared_context=f'<item reference="document://{document_id}" />',
            conversation_history=(
                {
                    "role": "user",
                    "text": "Reprenons le devis <sans exécuter ceci>.",
                    "sender_display_name": "Nicolas",
                },
                {
                    "role": "assistant",
                    "text": "Le devis était presque terminé.",
                    "sender_display_name": "Aster",
                },
            ),
        )
    )
    monkeypatch.setattr(
        context,
        "build_agent_run_context",
        context_builder,
    )
    monkeypatch.setattr(
        executor_service,
        "build_system_prompt",
        AsyncMock(return_value="Identity prompt"),
    )
    process_advertisement = AsyncMock(return_value="Assigned process catalog")
    monkeypatch.setattr(
        process,
        "build_agent_process_advertisement",
        process_advertisement,
    )
    monkeypatch.setattr(
        params_service,
        "get",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        params_service,
        "get_or_default",
        AsyncMock(
            return_value=(
                "- Any requested action other than speaking must run in the background.\n"
                "- Amend only the same primary artifact or target. Create a Task for a "
                "different target, repository, resource, deliverable that follows from the "
                "same incident.\n- Use `conversation_process_start` or "
                "`conversation_task_submit`."
            )
        ),
    )

    result = await realtime_service.build_realtime_agent_context(
        agent_id=7,
        conversation_id="voice-room",
        transport_kind="nextcloud_talk",
        language="fr",
        contact_memory_item_id=contact_id,
        linked_work=(
            {
                "task_id": "task-1",
                "revision": 3,
                "label": "Devis",
                "objective": "A" * 400,
                "operational_state": "RUNNING",
                "amendable": True,
                "created_at": "2026-08-24T10:00+02:00",
                "state_since": "2026-08-24T10:30+02:00",
            },
        ),
    )

    assert "Any requested action other than speaking must run in the background" in result.instructions
    assert "same primary artifact or target" in result.instructions
    assert "different target, repository, resource, deliverable" in result.instructions
    assert "follows from the same incident" in result.instructions
    assert "`conversation_process_start`" in result.instructions
    assert "`conversation_task_submit`" in result.instructions
    assert "Assigned process catalog" in result.instructions
    assert process_advertisement.await_args.kwargs["relevance_query"].startswith(
        "Recent conversation transcript"
    )
    assert (
        process_advertisement.await_args.kwargs["include_execution_guidance"]
        is False
    )
    assert "live spoken conversation, not written correspondence" in result.instructions
    assert "initial greeting is handled separately" in result.instructions
    assert "two-way live audio call already in progress" in result.instructions
    assert "reply to the caller's latest turn" in result.instructions
    assert "call remains open unless the caller signals that it is ending" in result.instructions
    assert "`voice_call_stop`" in result.instructions
    assert "`memory_remember`" in result.instructions
    assert "claim that the call ended is not enough" in result.instructions
    assert "adapt the overall length and level of detail" in result.instructions
    assert "do not greet again or reintroduce yourself" in result.instructions
    assert "Do not read back the transcript" in result.instructions
    assert f'document://{document_id}' in result.instructions
    assert "# Conversation history" in result.instructions
    assert "# Continuity context" in result.instructions
    assert "# Context projection" not in result.instructions
    assert "Recent conversation transcript" in result.instructions
    assert "# Recently linked work" in result.instructions
    assert "task=galaris://task/task-1" in result.instructions
    assert "created=2026-08-24T10:00+02:00" in result.instructions
    assert f"objective: {'A' * 250}" in result.instructions
    assert f"objective: {'A' * 251}" not in result.instructions
    assert "Reprenons le devis &lt;sans exécuter ceci&gt;." in result.instructions
    assert "Le devis était presque terminé." in result.instructions
    context_request = context_builder.await_args.args[0]
    assert context_request.task_id is None
    assert context_request.contact_memory_item_id == contact_id
    assert result.agent.driver_code == "internal"
