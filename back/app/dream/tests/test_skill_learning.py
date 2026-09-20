from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.dream.contracts import TaskOutcomeEvidence, TaskOutcomeEvidenceItem
from app.dream.mechanisms.skill_learning import (
    _validated_decision,
    skill_learning_mechanism,
)
from app.dream.registry import mechanisms, register_default_mechanisms, reset_registry
from app.skill.learning_contracts import LearnedSkillDecision, LearnedSkillOperation
from app.task.models import Task, TaskStatus
from core.params import runtime_settings


def test_skill_learning_rejects_unknown_evidence_and_unjustified_weakening() -> None:
    target_id = uuid4()
    evidence = TaskOutcomeEvidence(
        task_id=uuid4(),
        owner_agent_id=7,
        terminal_status="SUCCESS",
        observations=[
            TaskOutcomeEvidenceItem(
                reference="tool:0:verify",
                kind="tool_result",
                status="success",
            )
        ],
        fingerprint="a" * 64,
    )
    decision = LearnedSkillDecision(
        operations=[
            LearnedSkillOperation(
                action="REINFORCE",
                target_skill_id=target_id,
                evidence_refs=["tool:9:invented"],
                rationale="Invented evidence is not admissible.",
                confidence=0.9,
            ),
            LearnedSkillOperation(
                action="WEAKEN",
                target_skill_id=target_id,
                evidence_refs=["tool:0:verify"],
                rationale="A verified success does not justify weakening.",
                confidence=0.9,
            ),
        ]
    )

    validated = _validated_decision(
        decision,
        evidence,
        {target_id: ("learned-agent-check", "")},
        "learned-agent-",
        "verified_tool_success",
    )

    assert validated.operations == []


def test_default_registry_uses_skill_learning_instead_of_memory_experience() -> None:
    reset_registry()
    try:
        register_default_mechanisms()
        keys = {mechanism.key for mechanism in mechanisms()}

        assert "skill.learn_task_outcome" in keys
        assert "memory.reflect_task_outcome" not in keys
    finally:
        reset_registry()
        register_default_mechanisms()


@pytest.mark.asyncio
async def test_skill_learning_counts_historical_terminal_tasks(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_settings, "DREAM_SKILL_LEARNING_MODE", "learn")
    suffix = uuid4().hex[:10]
    title = Title(label=f"Historical learning {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="History",
        code=f"history-{suffix}",
        agent_driver="internal",
    )
    db.add(owner)
    await db.flush()
    historical = Task(
        label="Historical terminal task",
        objective="Apply the same verified procedure.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    active = Task(
        label="Active task",
        objective="This task is not terminal.",
        status=TaskStatus.EXEC,
        agent_id=owner.id,
    )
    db.add_all((historical, active))
    await db.commit()

    assert await skill_learning_mechanism.count_pending() == 1
