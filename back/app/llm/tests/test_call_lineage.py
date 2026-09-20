from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection
from app.conversation import ConversationRound, ConversationTaskLink
from app.llm import llm_call_service
from app.llm.models import LLMCall
from app.llm.purposes import LLMCallPurpose
from app.messenger import Room
from app.task.models import Task, TaskAttempt, TaskStatus
from app.tools.models import Tool


@pytest.mark.asyncio
async def test_batch_activity_excludes_other_runs_auxiliary_calls_and_unmanaged_agents(db):
    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    agents = [Agent(code=f"batch-{uuid4()}", first_name="Agent", last_name=str(i), title_id=title.id) for i in range(2)]
    db.add_all(agents)
    await db.flush()
    tasks = [Task(label="Task", objective="Work", agent_id=agent.id) for agent in agents]
    db.add_all(tasks)
    await db.flush()
    current, old = uuid4(), uuid4()
    calls = [LLMCall(task_id=task.id, agent_id=task.agent_id, agent_run_id=run,
                     correlation_ref=auxiliary, provider_name="test", requested_model="test")
             for task, run, auxiliary in [(tasks[0], current, None), (tasks[0], old, None),
                                           (tasks[0], current, "auxiliary"), (tasks[1], current, None)]]
    db.add_all(calls)
    await db.flush()
    actual = await llm_call_service.list_calls(task_ids=[task.id for task in tasks],
                                              agent_run_ids=[current], agent_ids={agents[0].id})
    assert [call.id for call in actual] == [calls[0].id]


@pytest.mark.parametrize(
    "purpose",
    [
        LLMCallPurpose.AGENT_BRIEFING,
        LLMCallPurpose.AGENT_PLANNING,
        LLMCallPurpose.AGENT_PLANNING_RECOVERY,
        LLMCallPurpose.AGENT_SYNTHESIS,
    ],
)
def test_first_party_task_purposes_reject_a_missing_task(
    purpose: LLMCallPurpose,
) -> None:
    with pytest.raises(ValueError, match="requires a Task"):
        llm_call_service._validate_semantic_lineage(  # pyright: ignore[reportPrivateUsage]
            purpose=purpose,
            task_id=None,
            task_attempt_id=None,
            conversation_round_id=None,
            process_run_id=None,
        )


@pytest.mark.parametrize(
    "purpose",
    [
        LLMCallPurpose.CONVERSATION_TEXT,
        LLMCallPurpose.CONVERSATION_AUDIO,
        LLMCallPurpose.CONVERSATION_TASK_OBJECTIVE,
    ],
)
def test_conversation_purposes_reject_a_missing_round(
    purpose: LLMCallPurpose,
) -> None:
    with pytest.raises(ValueError, match="requires a conversation round"):
        llm_call_service._validate_semantic_lineage(  # pyright: ignore[reportPrivateUsage]
            purpose=purpose,
            task_id=None,
            task_attempt_id=None,
            conversation_round_id=None,
            process_run_id=None,
        )


def test_task_agent_call_rejects_a_missing_attempt() -> None:
    with pytest.raises(RuntimeError, match="has no active attempt"):
        llm_call_service._validate_semantic_lineage(  # pyright: ignore[reportPrivateUsage]
            purpose=LLMCallPurpose.AGENT_EXEC,
            task_id=uuid4(),
            task_attempt_id=None,
            conversation_round_id=None,
            process_run_id=None,
        )


def test_dispatcher_requires_a_task_or_round() -> None:
    with pytest.raises(ValueError, match="requires a Task or conversation round"):
        llm_call_service._validate_semantic_lineage(  # pyright: ignore[reportPrivateUsage]
            purpose=LLMCallPurpose.AGENT_DISPATCH,
            task_id=None,
            task_attempt_id=None,
            conversation_round_id=None,
            process_run_id=None,
        )


def test_process_purpose_rejects_a_missing_process_run() -> None:
    with pytest.raises(ValueError, match="requires a ProcessRun"):
        llm_call_service._validate_semantic_lineage(  # pyright: ignore[reportPrivateUsage]
            purpose=LLMCallPurpose.PROCESS_EXEC,
            task_id=None,
            task_attempt_id=None,
            conversation_round_id=None,
            process_run_id=None,
        )


@pytest.mark.asyncio
async def test_tool_results_are_scoped_to_the_exact_task_under_parallel_runs(
    db: AsyncSession,
) -> None:
    first_task = Task(id=uuid4(), label="First parallel task")
    second_task = Task(id=uuid4(), label="Second parallel task")
    db.add_all([first_task, second_task])
    await db.flush()
    first_call = LLMCall(
        task_id=first_task.id,
        provider_name="test-provider",
        requested_model="test-model",
        effective_model="test-model",
        request_messages=[{"role": "user", "content": "first"}],
        tool_calls=[{"id": "reused-tool-id", "name": "read"}],
    )
    second_call = LLMCall(
        task_id=second_task.id,
        provider_name="test-provider",
        requested_model="test-model",
        effective_model="test-model",
        request_messages=[{"role": "user", "content": "second"}],
        tool_calls=[{"id": "reused-tool-id", "name": "read"}],
    )
    db.add_all([first_call, second_call])
    await db.commit()

    await llm_call_service.attach_tool_results(
        messages=[
            {
                "role": "tool",
                "tool_call_id": "reused-tool-id",
                "content": "first result",
            }
        ],
        agent_id=None,
        task_id=first_task.id,
    )

    await db.refresh(first_call)
    await db.refresh(second_call)
    assert first_call.tool_calls[0]["result"] == "first result"
    assert "result" not in second_call.tool_calls[0]


def test_task_owned_calls_can_retain_conversation_and_process_provenance() -> None:
    predicates = llm_call_service.task_owned_call_predicates()

    assert len(predicates) == 2
    assert all("conversation_round_id" not in str(item) for item in predicates)
    process_predicate = str(predicates[0])
    assert "process_run_id IS NULL" in process_predicate
    assert "purpose IN" in process_predicate


@pytest.mark.asyncio
async def test_one_call_is_visible_from_both_task_and_conversation_round(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:10]
    title = Title(label=f"LLM lineage {suffix}", gender="X")
    tool = Tool(
        code=f"llm-lineage-{suffix}",
        label="LLM lineage transport",
        description="",
        connection_schema={},
        conversation_enabled=True,
    )
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Lineage",
        last_name="Test",
        code=f"llm-lineage-agent-{suffix}",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"room-{suffix}",
        label="Lineage room",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    round_ = ConversationRound(room_id=room.id, status="RUNNING")
    db.add(round_)
    await db.flush()
    task = Task(
        label="Round-owned task",
        objective="Keep both durable owners",
        agent_id=agent.id,
        data={"conversation_round_id": str(round_.id)},
    )
    db.add(task)
    await db.flush()
    db.add(
        ConversationTaskLink(
            round_id=round_.id,
            task_id=task.id,
            action_key=f"action-{suffix}",
        )
    )
    call = LLMCall(
        task_id=task.id,
        conversation_round_id=round_.id,
        agent_id=agent.id,
        purpose="agent.dispatch",
        provider_name="test-provider",
        requested_model="test-model",
        effective_model="test-model",
    )
    db.add(call)
    await db.commit()

    assert [item.id for item in await llm_call_service.list_calls(task_id=task.id)] == [
        call.id
    ]
    assert [
        item.id
        for item in await llm_call_service.list_calls(
            conversation_round_id=round_.id
        )
    ] == [call.id]


@pytest.mark.asyncio
async def test_task_call_lineage_binds_current_attempt_and_conversation_round(
    db: AsyncSession,
) -> None:
    task_id = uuid4()
    lease_token = uuid4()
    round_id = uuid4()
    process_run_id = uuid4()
    task = Task(
        id=task_id,
        label="Conversation work",
        objective="Produce the requested report",
        status=TaskStatus.DISPATCH,
        lease_token=lease_token,
        data={
            "conversation_round_id": str(round_id),
            "process_run_id": str(process_run_id),
        },
    )
    attempt = TaskAttempt(
        task_id=task_id,
        attempt_number=1,
        phase="EXEC",
        status="CLAIMED",
        worker_id="test-worker",
        lease_token=lease_token,
    )
    db.add_all([task, attempt])
    await db.commit()

    objective, attempt_id, resolved_round_id, resolved_process_run_id = (
        await llm_call_service._task_call_lineage(  # pyright: ignore[reportPrivateUsage]
            task_id=task_id,
            agent_id=None,
            conversation_round_id=None,
        )
    )

    assert objective == task.objective
    assert attempt_id == attempt.id
    assert resolved_round_id == round_id
    assert resolved_process_run_id == process_run_id


@pytest.mark.asyncio
async def test_task_call_lineage_rejects_an_explicit_foreign_round(
    db: AsyncSession,
) -> None:
    expected_round_id = uuid4()
    task = Task(
        id=uuid4(),
        label="Conversation work",
        objective="Keep lineage exact",
        data={"conversation_round_id": str(expected_round_id)},
    )
    db.add(task)
    await db.commit()

    with pytest.raises(ValueError, match="belongs to conversation round"):
        await llm_call_service._task_call_lineage(  # pyright: ignore[reportPrivateUsage]
            task_id=task.id,
            agent_id=None,
            conversation_round_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_task_call_lineage_rejects_an_explicit_foreign_process(
    db: AsyncSession,
) -> None:
    expected_process_run_id = uuid4()
    task = Task(
        id=uuid4(),
        label="Process work",
        objective="Keep Process lineage exact",
        data={"process_run_id": str(expected_process_run_id)},
    )
    db.add(task)
    await db.commit()

    with pytest.raises(ValueError, match="belongs to ProcessRun"):
        await llm_call_service._task_call_lineage(  # pyright: ignore[reportPrivateUsage]
            task_id=task.id,
            agent_id=None,
            conversation_round_id=None,
            process_run_id=uuid4(),
        )
