import inspect
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.conversation import ConversationTurn
from app.conversation import mcp as conversation_mcp
from app.conversation.models import ConversationTaskLink
from app.agent.contracts import (
    ExecutionResult,
    ReasoningEffort,
    WorkingResource,
    WorkingSet,
)
from app.task import amendment_service
from app.task.models import Task, TaskStatus
from app.task.schemas import TaskCreate
from app.task.working_set import WORKING_SET_DATA_KEY
from app.tools import McpToolContext


def _turn(
    *,
    topic_id: UUID | None = None,
    contact_memory_item_id: UUID | None = None,
    reasoning_effort_override: ReasoningEffort | None = None,
    messages: tuple[dict[str, object], ...] = (),
) -> ConversationTurn:
    return ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=7,
        language="fr",
        objective="Ajoute aussi une version PDF.",
        messages=messages,
        messaging_context={
            "connection_id": 19,
            "tool_id": 23,
            "platform": "matrix",
            "room_id": "room-1",
            "participant_id": "nicolas",
        },
        topic_id=topic_id,
        reasoning_effort_override=reasoning_effort_override,
        contact_memory_item_id=contact_memory_item_id,
    )


def _task(**values: object) -> Task:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "revision": 4,
        "label": "Rapport",
        "objective": "Préparer le rapport.",
        "status": TaskStatus.DISPATCH,
        "paused": False,
        "ai": True,
        "cost": 0.0,
        "agent_id": 7,
        "messenger_connection_id": 19,
        "message_platform": "matrix",
        "message_group_id": "room-1",
    }
    defaults.update(values)
    return Task(**defaults)


@pytest.mark.asyncio
async def test_superseded_document_presentation_is_control_flow_not_permission_failure(monkeypatch):
    from app.conversation import ConversationSuperseded, document_display

    turn = replace(_turn(), assert_fresh_before_effect=AsyncMock(return_value=False))
    authorize = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(document_display, "can_display_conversation_document", AsyncMock(return_value=True))
    monkeypatch.setattr(document_display, "_authorize_read", authorize)
    monkeypatch.setattr(document_display, "_publisher", publish)
    document_id = uuid4()
    with pytest.raises(ConversationSuperseded):
        await document_display.display_conversation_document(turn, document_id)
    authorize.assert_awaited_once_with(document_id, turn.agent_id)
    publish.assert_not_awaited()


def test_task_submit_does_not_expose_an_effort_control() -> None:
    parameters = inspect.signature(conversation_mcp.conversation_task_submit).parameters

    assert "effort" not in parameters


def test_dispatch_controls_are_normalized_before_task_creation() -> None:
    assert conversation_mcp._dispatch_forces("auto") == (None, None)
    assert conversation_mcp._dispatch_forces("exec") == ("EXEC", None)
    assert conversation_mcp._dispatch_forces("plan") == ("PLAN", "high")
    assert conversation_mcp._dispatch_forces("briefing") == (
        "BRIEFING",
        "high",
    )


@pytest.mark.asyncio
async def test_task_submit_leaves_exec_effort_to_the_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    create = AsyncMock(return_value={"created": True})
    monkeypatch.setattr(conversation_mcp, "_create_conversation_task", create)
    monkeypatch.setattr(conversation_mcp, "_validate_dispatch_mode", AsyncMock())
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_task_submit(
        ctx,
        objective="Contrôle puis pousse le dépôt.",
        mode="exec",
    )

    assert result == {"created": True}
    assert create.await_args.kwargs["normalized_effort"] == "standard"
    assert create.await_args.kwargs["forced_route"] == "EXEC"
    assert create.await_args.kwargs["forced_effort"] is None


@pytest.mark.asyncio
async def test_task_submit_forwards_explicit_briefing_to_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    create = AsyncMock(return_value={"created": True})
    validate_mode = AsyncMock()
    monkeypatch.setattr(conversation_mcp, "_create_conversation_task", create)
    monkeypatch.setattr(conversation_mcp, "_validate_dispatch_mode", validate_mode)
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_task_submit(
        ctx,
        objective="Fais-le avec le contexte complet.",
        mode="briefing",
    )

    assert result == {"created": True}
    validate_mode.assert_awaited_once_with(turn, "briefing")
    assert create.await_args.kwargs["forced_route"] == "BRIEFING"
    assert create.await_args.kwargs["forced_effort"] == "high"


@pytest.mark.asyncio
async def test_explicit_briefing_is_unavailable_while_policy_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    monkeypatch.setattr(
        "app.agent.get_agent_record",
        AsyncMock(return_value=SimpleNamespace(agent_driver="internal")),
    )

    with pytest.raises(ValueError, match="briefing is unavailable"):
        await conversation_mcp._validate_dispatch_mode(turn, "briefing")


@pytest.mark.asyncio
async def test_direct_admission_forwards_task_dispatch_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    fresh = AsyncMock(return_value=turn)
    create = AsyncMock(return_value={"created": True})

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    monkeypatch.setattr("core.database.get_db_session", fake_db_session)
    monkeypatch.setattr(conversation_mcp, "_fresh", fresh)
    validate_mode = AsyncMock()
    monkeypatch.setattr(conversation_mcp, "_validate_dispatch_mode", validate_mode)
    monkeypatch.setattr(conversation_mcp, "_create_conversation_task", create)

    result = await conversation_mcp.admit_background_task(
        turn,
        "  Fais ça  ",
        forced_route="PLAN",
        forced_effort="high",
        auto_approve=True,
    )

    assert result == {"created": True}
    assert create.await_args.kwargs["clean_objective"] == "Fais ça"
    assert create.await_args.kwargs["normalized_effort"] == "high"
    assert create.await_args.kwargs["forced_route"] == "PLAN"
    assert create.await_args.kwargs["forced_effort"] == "high"
    assert create.await_args.kwargs["auto_approve"] is True
    validate_mode.assert_awaited_once_with(turn, "plan")


@pytest.mark.asyncio
async def test_task_creation_is_cancelled_when_turn_becomes_stale_during_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freshness = AsyncMock(return_value=False)
    turn = replace(_turn(), assert_fresh_before_effect=freshness)
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    generate = AsyncMock(return_value=("Rapport", "Objectif complet", 0.01))
    lineage = AsyncMock()
    monkeypatch.setattr(conversation_mcp, "get_db", lambda: db)
    monkeypatch.setattr(conversation_mcp, "generate_task_fields", generate)
    monkeypatch.setattr(conversation_mcp, "_turn_lineage", lineage)
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    with pytest.raises(asyncio.CancelledError, match="while the Task objective was being built"):
        await conversation_mcp.conversation_task_submit(
            ctx,
            label="Rapport",
            objective="Vas-y.",
        )

    assert freshness.await_count == 1
    generate.assert_awaited_once()
    lineage.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_post_cancels_blocked_objective_before_any_task_is_created(monkeypatch):
    entered = asyncio.Event()
    pending = asyncio.Event()
    cancelled = asyncio.Event()
    async def generate(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    async def newer_input():
        return pending.is_set()
    turn = replace(_turn(), should_interrupt=newer_input)
    monkeypatch.setattr(conversation_mcp, "_existing_admitted_task", AsyncMock(return_value=None))
    monkeypatch.setattr(conversation_mcp, "generate_task_fields", generate)
    lineage = AsyncMock()
    monkeypatch.setattr(conversation_mcp, "_turn_lineage", lineage)
    run = asyncio.create_task(conversation_mcp._create_conversation_task(turn,
        clean_label="Report", clean_objective="Prepare report", normalized_effort="standard",
        action_key="one-action", requested_disposition="CREATE_NEW"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        pending.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run, 2)
        assert cancelled.is_set()
        lineage.assert_not_awaited()
    finally:
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)


@pytest.mark.asyncio
async def test_idempotent_retry_does_not_rebuild_an_existing_task_objective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    existing = _task()
    lookup = AsyncMock(return_value=existing)
    creation_result = AsyncMock(return_value={"created": False, "id": str(existing.id)})
    generate = AsyncMock()
    monkeypatch.setattr(conversation_mcp, "_existing_admitted_task", lookup)
    monkeypatch.setattr(conversation_mcp, "_creation_result", creation_result)
    monkeypatch.setattr(conversation_mcp, "generate_task_fields", generate)

    result = await conversation_mcp._create_conversation_task(
        turn,
        clean_label="Rapport",
        clean_objective="Construire le rapport.",
        normalized_effort="standard",
        action_key="submit:stable",
        requested_disposition="CREATE_NEW",
    )

    assert result["created"] is False
    lookup.assert_awaited_once_with(turn, "submit:stable")
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_turn_lineage_respects_a_cleared_durable_round_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn(topic_id=uuid4(), contact_memory_item_id=uuid4())
    db = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                topic_id=None,
                contact_memory_item_id=None,
            )
        )
    )
    monkeypatch.setattr(conversation_mcp, "get_db", lambda: db)

    assert await conversation_mcp._turn_lineage(turn) == (None, None)


@pytest.mark.asyncio
async def test_free_form_choice_resolution_uses_the_exact_turn_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn(messages=({"text": "Non, surtout pas comme ça."},))
    freshness = AsyncMock(return_value=True)
    turn = replace(turn, assert_fresh_before_effect=freshness)
    resolution = SimpleNamespace(
        interaction_id=uuid4(),
        kind="hermes_approval",
        option_id="deny",
    )
    resolve = AsyncMock(return_value=(resolution, True))
    monkeypatch.setattr("app.messenger.resolve_pending_choice", resolve)
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_choice_resolve(
        ctx,
        reference="#DEC1DE42",
        option_id="deny",
    )

    freshness.assert_awaited_once()
    resolve.assert_awaited_once_with(
        reference="#DEC1DE42",
        option_id="deny",
        response_text="Non, surtout pas comme ça.",
        agent_id=7,
        connection_id=19,
        tool_id=23,
        room_id="room-1",
        user_id="nicolas",
    )
    assert result["status"] == "RESOLVED"


@pytest.mark.asyncio
async def test_existing_attachment_delivery_cannot_create_a_generation_task() -> None:
    base = _turn()
    turn = ConversationTurn(
        room_id=base.room_id,
        round_id=base.round_id,
        agent_id=base.agent_id,
        language=base.language,
        objective="Joins-moi le fichier HTML V2 déjà créé.",
        messages=base.messages,
        messaging_context=base.messaging_context,
    )
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    with pytest.raises(ValueError, match="existing attachment"):
        await conversation_mcp.conversation_task_submit(
            ctx,
            label="Générer une nouvelle V3",
            objective="Crée une nouvelle page HTML 3D et livre-la.",
        )


@pytest.mark.asyncio
async def test_task_list_summary_omits_result_and_keeps_resource_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task(
        objective="o" * 900,
        last_error="e" * 900,
        data={
            WORKING_SET_DATA_KEY: WorkingSet(
                version=1,
                resources=[
                    WorkingResource(
                        resource_type="file",
                        role="final_artifact",
                        reference="report.pdf",
                        label="Rapport final",
                    )
                ],
            ).model_dump(mode="json")
        },
    )
    task.set_execution_result(
        ExecutionResult(prompt="p", result="r" * 20_000, success=True)
    )
    monkeypatch.setattr(
        "app.task.operational_state.inspect_operational_state",
        AsyncMock(return_value={"operational_state": "EXECUTING"}),
    )

    result = await conversation_mcp._task_summary_dict(task)

    assert "result" not in result
    assert len(result["objective"]) == 500
    assert len(result["last_error"]) == 500
    assert result["working_set"] == [
        {
            "resource_type": "file",
            "role": "final_artifact",
            "reference": "report.pdf",
            "label": "Rapport final",
            "revision": None,
            "state": "active",
        }
    ]


@pytest.mark.asyncio
async def test_created_task_inherits_latest_round_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic_id = uuid4()
    contact_id = uuid4()
    current_id = uuid4()
    turn = _turn(
        reasoning_effort_override="xhigh",
        messages=(
            {
                "messenger_message_id": str(current_id),
                "external_message_id": "current-remote-id",
                "text": "Construis une scène 3D.",
                "sender_external_id": "nicolas",
                "sender_display_name": "Nicolas",
            },
        )
    )
    created_task = _task(id=uuid4(), status=TaskStatus.CREATE)
    built: list[TaskCreate] = []
    added: list[object] = []
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        get=AsyncMock(
            return_value=SimpleNamespace(
                topic_id=topic_id,
                contact_memory_item_id=contact_id,
                requester_user_id=None,
            )
        ),
        add=added.append,
        flush=AsyncMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    monkeypatch.setattr(conversation_mcp, "get_db", lambda: db)
    monkeypatch.setattr(
        "app.task.task_service.build",
        lambda task_data: built.append(task_data) or created_task,
    )
    monkeypatch.setattr("app.task.task_service.publish_created", AsyncMock())
    monkeypatch.setattr("app.task.runner.go_next", lambda _task_id: None)
    monkeypatch.setattr(
        "app.task.operational_state.inspect_operational_state",
        AsyncMock(return_value={}),
    )
    generate = AsyncMock(
        return_value=(
            "Scène 3D complète",
            "<p>Construire la scène 3D complète avec toutes les ressources citées.</p>",
            0.125,
        )
    )
    monkeypatch.setattr(conversation_mcp, "generate_task_fields", generate)
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_task_submit(
        ctx,
        label="Rapport",
        objective="Préparer le rapport.",
    )

    assert result["created"] is True
    assert created_task.topic_id == topic_id
    assert created_task.contact_memory_item_id == contact_id
    task_create = built[0]
    assert task_create.label == "Scène 3D complète"
    from core.util import visible_text

    assert turn.objective in visible_text(task_create.objective)
    assert "Construire la scène 3D complète avec toutes les ressources citées." in visible_text(task_create.objective)
    assert task_create.cost == 0.125
    assert task_create.reasoning_effort_override == "xhigh"
    assert task_create.data["message_id"] == "current-remote-id"
    assert task_create.data["text"] == "Construis une scène 3D."
    assert task_create.data["room_id"] == "room-1"
    assert task_create.data["group_id"] == "room-1"
    assert task_create.data["connection_id"] == 19
    assert task_create.data["sender.user_id"] == "nicolas"
    assert task_create.data["sender.nickname"] == "Nicolas"
    assert task_create.data["sender.display_name"] == "Nicolas"
    assert task_create.data["objective_is_standalone"] is True
    assert task_create.messages is None
    generate.assert_awaited_once_with(
        turn,
        label_hint="Rapport",
        objective_hint="Préparer le rapport.",
    )
    assert created_task in added
    assert visible_text(created_task.data["_original_demand"]) == turn.objective
    timing = created_task.data["_startup_timing"]
    started = datetime.fromisoformat(timing["preparation_started_at"])
    finished = datetime.fromisoformat(timing["preparation_finished_at"])
    enqueued = datetime.fromisoformat(timing["enqueued_at"])
    assert started <= finished <= enqueued <= datetime.now(timezone.utc)
    link = next(item for item in added if isinstance(item, ConversationTaskLink))
    assert link.round_id == turn.round_id
    assert link.task_id == created_task.id


@pytest.mark.asyncio
async def test_admission_amends_the_same_current_deliverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    task = _task(
        paused=True,
        data={"pause_reasons": ["await"]},
    )
    amendment = SimpleNamespace(id=uuid4())
    amend = AsyncMock(
        return_value=amendment_service.TaskAmendmentResult(
            task=task,
            amendment=amendment,
            created=True,
            interrupted=False,
        )
    )
    monkeypatch.setattr(conversation_mcp, "_visible_task", AsyncMock(return_value=task))
    monkeypatch.setattr(amendment_service, "amend_task", amend)
    monkeypatch.setattr(
        "app.task.operational_state.inspect_operational_state",
        AsyncMock(
            return_value={
                "operational_state": "WAITING",
                "resume_phase": "DISPATCH",
                "pause_reasons": ["await"],
                "waits": [],
                "amendable": True,
                "amend_blocker": None,
            }
        ),
    )
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_task_submit(
        ctx,
        label="Rapport",
        objective="Ajouter aussi une version PDF.",
        disposition="AMEND_CURRENT",
        target_task_id=str(task.id),
        expected_revision=4,
        reason="Même livrable.",
    )

    assert result["created"] is False
    assert result["amended"] is True
    assert result["action"] == "AMEND_CURRENT"
    amend.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_conversation_amendment_returns_conflict_without_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    task = _task(message_group_id="another-room")
    monkeypatch.setattr(conversation_mcp, "_visible_task", AsyncMock(return_value=task))
    create = AsyncMock(
        return_value={
            "created": True,
            "amended": False,
            "action": "CREATE_NEW",
            "queued": True,
        }
    )
    monkeypatch.setattr(conversation_mcp, "_create_conversation_task", create)
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_task_submit(
        ctx,
        label="Rapport",
        objective="Ajouter une version PDF.",
        disposition="AMEND_CURRENT",
        target_task_id=str(task.id),
        expected_revision=4,
    )

    assert result["created"] is False
    assert result["action"] == "CONFLICT"
    create.assert_not_awaited()
    assert result["conflict"] == (
        "amendment_target_outside_conversation"
    )


@pytest.mark.asyncio
async def test_incomplete_amendment_returns_conflict_without_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    create = AsyncMock(
        return_value={
            "created": True,
            "amended": False,
            "action": "CREATE_NEW",
            "queued": True,
        }
    )
    monkeypatch.setattr(conversation_mcp, "_create_conversation_task", create)
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_task_submit(
        ctx,
        label="Rapport",
        objective="Changer le modèle.",
        disposition="AMEND_QUEUED",
        target_task_id=str(uuid4()),
    )

    assert result["created"] is False
    assert result["action"] == "CONFLICT"
    create.assert_not_awaited()
    assert result["conflict"] == (
        "incomplete_amendment_target"
    )


@pytest.mark.asyncio
async def test_queued_task_amendment_is_normalized_after_agent_slot_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    task = _task(status=TaskStatus.CREATE)
    amendment = SimpleNamespace(id=uuid4())
    amend = AsyncMock(
        return_value=amendment_service.TaskAmendmentResult(
            task=task,
            amendment=amendment,
            created=True,
            interrupted=False,
        )
    )
    monkeypatch.setattr(conversation_mcp, "_visible_task", AsyncMock(return_value=task))
    monkeypatch.setattr(amendment_service, "amend_task", amend)
    monkeypatch.setattr(
        "app.task.operational_state.inspect_operational_state",
        AsyncMock(
            return_value={
                "operational_state": "QUEUED",
                "resume_phase": "CREATE",
                "pause_reasons": [],
                "waits": [],
                "amendable": True,
                "amend_blocker": None,
            }
        ),
    )
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_task_submit(
        ctx,
        objective="Ajouter aussi une version PDF.",
        disposition="AMEND_CURRENT",
        target_task_id=str(task.id),
        expected_revision=4,
    )

    assert result["amended"] is True
    assert result["action"] == "AMEND_QUEUED"
    assert result["requested_action"] == "AMEND_CURRENT"
    assert amend.await_args.kwargs["disposition"] == "AMEND_QUEUED"


@pytest.mark.asyncio
@pytest.mark.parametrize("during_write", [False, True])
async def test_unavailable_amendment_requires_explicit_creation_for_new_work(
    monkeypatch: pytest.MonkeyPatch,
    during_write: bool,
) -> None:
    turn = _turn()
    task = _task(plan={"steps": [{"label": "Already running"}]})
    create = AsyncMock(
        return_value={
            "created": True,
            "amended": False,
            "action": "CREATE_NEW",
            "queued": True,
        }
    )
    monkeypatch.setattr(conversation_mcp, "_visible_task", AsyncMock(return_value=task))
    monkeypatch.setattr(conversation_mcp, "_create_conversation_task", create)
    monkeypatch.setattr(
        "app.task.operational_state.inspect_operational_state",
        AsyncMock(
            return_value={
                "operational_state": "RUNNING",
                "resume_phase": "PLAN",
                "pause_reasons": [],
                "waits": [],
                "amendable": during_write,
                "amend_blocker": "A Task with a materialized plan cannot be amended safely.",
            }
        ),
    )
    if during_write:
        from app.task.task_service import TaskEditConflict

        monkeypatch.setattr(amendment_service, "amend_task", AsyncMock(
            side_effect=TaskEditConflict("Task changed before the locked amendment."),
        ))
        monkeypatch.setattr(conversation_mcp, "get_db", lambda: SimpleNamespace(commit=AsyncMock()))
    ctx = McpToolContext(
        agent_id=7,
        runtime="internal",
        resources={"conversation_turn": turn},
    )

    result = await conversation_mcp.conversation_task_submit(
        ctx,
        objective="Produire aussi un autre livrable indépendant.",
        disposition="AMEND_CURRENT",
        target_task_id=str(task.id),
        expected_revision=4,
    )

    assert result["created"] is False
    assert result["action"] == "CONFLICT"
    assert result["conflict"] == "amendment_no_longer_safe"
    create.assert_not_awaited()

    result = await conversation_mcp.conversation_task_submit(
        ctx, objective="Produire un autre livrable indépendant.", disposition="CREATE_NEW",
    )
    assert result["created"] is True
    create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["agent", "room"])
async def test_scope_change_during_amendment_does_not_leak_the_new_definition(monkeypatch, scope):
    from app.task.task_service import TaskRevisionConflict

    task = _task()
    monkeypatch.setattr(conversation_mcp, "_visible_task", AsyncMock(return_value=task))
    monkeypatch.setattr("app.task.operational_state.inspect_operational_state", AsyncMock(return_value={
        "amendable": True, "operational_state": "QUEUED",
    }))
    async def amend(**kwargs):
        if scope == "agent":
            task.agent_id = 8
        else:
            task.message_group_id = "private-room"
        task.objective = "<p>private transferred content</p>"
        raise TaskRevisionConflict("scope changed")
    monkeypatch.setattr(amendment_service, "amend_task", amend)
    create = AsyncMock()
    monkeypatch.setattr(conversation_mcp, "_create_conversation_task", create)
    ctx = McpToolContext(agent_id=7, runtime="internal", resources={"conversation_turn": _turn()})
    result = await conversation_mcp.conversation_task_submit(ctx, objective="Add PDF",
        disposition="AMEND_QUEUED", target_task_id=str(task.id), expected_revision=4)
    assert result["conflict"] == "amendment_target_unavailable"
    assert "private" not in str(result)
    assert "conversation_task_definitions" not in ctx.resources
    create.assert_not_awaited()
