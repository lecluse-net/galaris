from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.skill import learning_service
from app.skill.learning_contracts import LearnedSkillDecision, LearnedSkillOperation


def _markdown(code: str, instruction: str = "Run the verified check.") -> str:
    return (
        "---\n"
        f"name: {code}\n"
        "description: Verify deployments when a health check is available.\n"
        "---\n\n"
        "# Deployment verification\n\n"
        f"{instruction}\n"
    )


def test_learning_mode_exposes_only_the_effective_feature_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        learning_service.runtime_settings,
        "DREAM_SKILL_LEARNING_MODE",
        "observe",
    )

    assert learning_service.learning_mode() == "observe"


async def _agent(db: AsyncSession) -> Agent:
    title = Title(label=f"Learning {uuid4().hex[:8]}", gender="M")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        code=f"learner-{uuid4().hex[:8]}",
        first_name="Learning",
        last_name="Agent",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    return agent


@pytest.mark.asyncio
async def test_learned_skill_requires_repeated_evidence_and_can_be_weakened(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = await _agent(db)
    monkeypatch.setattr(learning_service.runtime_settings, "DREAM_SKILL_MIN_EVIDENCE", 3)
    monkeypatch.setattr(learning_service.runtime_settings, "DREAM_SKILL_ACTIVATION_SCORE", 0.75)
    monkeypatch.setattr(learning_service.runtime_settings, "DREAM_SKILL_MAX_ACTIVE", 20)
    code = f"learned-{agent.code}-deployment-check"
    reference = "tool:0:health"

    created = await learning_service.apply_learning_decision(
        agent_id=agent.id,
        source_ref=f"galaris://task/{uuid4()}",
        source_fingerprint="a" * 64,
        allowed_evidence_refs={reference},
        evidence_weight=0.8,
        decision=LearnedSkillDecision(
            operations=[
                LearnedSkillOperation(
                    action="CREATE",
                    code=code,
                    label="Deployment check",
                    markdown=_markdown(code),
                    evidence_refs=[reference],
                    rationale="The health tool verified the deployment.",
                    confidence=0.9,
                )
            ]
        ),
    )
    await db.flush()
    record = (await learning_service.list_learning_context(agent.id))[0]
    assert created.changed == 1
    assert record.evidence_count == 1
    assert record.injectable is False

    for fingerprint in ("b" * 64, "c" * 64):
        result = await learning_service.apply_learning_decision(
            agent_id=agent.id,
            source_ref=f"galaris://task/{uuid4()}",
            source_fingerprint=fingerprint,
            allowed_evidence_refs={reference},
            evidence_weight=0.8,
            decision=LearnedSkillDecision(
                operations=[
                    LearnedSkillOperation(
                        action="REINFORCE",
                        target_skill_id=record.id,
                        evidence_refs=[reference],
                        rationale="An independent Task confirmed the procedure.",
                        confidence=0.85,
                    )
                ]
            ),
        )
        assert result.changed == 1
    await db.flush()

    injectable = await learning_service.list_injectable(agent.id)
    assert [item.id for item in injectable] == [record.id]
    assert injectable[0].evidence_count == 3
    assert injectable[0].score > 0.75

    weakened = await learning_service.apply_learning_decision(
        agent_id=agent.id,
        source_ref=f"galaris://task/{uuid4()}",
        source_fingerprint="d" * 64,
        allowed_evidence_refs={reference},
        evidence_weight=1.0,
        decision=LearnedSkillDecision(
            operations=[
                LearnedSkillOperation(
                    action="WEAKEN",
                    target_skill_id=record.id,
                    evidence_refs=[reference],
                    rationale="The procedure contradicted the observed health result.",
                    confidence=0.9,
                )
            ]
        ),
    )
    await db.flush()
    assert weakened.refresh_required is True
    assert await learning_service.list_injectable(agent.id) == []


@pytest.mark.asyncio
async def test_learning_evidence_is_idempotent(
    db: AsyncSession,
) -> None:
    agent = await _agent(db)
    code = f"learned-{agent.code}-idempotent-check"
    decision = LearnedSkillDecision(
        operations=[
            LearnedSkillOperation(
                action="CREATE",
                code=code,
                label="Idempotent check",
                markdown=_markdown(code),
                evidence_refs=["tool:0:check"],
                rationale="A verified check supplied one reusable signal.",
                confidence=0.8,
            )
        ]
    )
    first = await learning_service.apply_learning_decision(
        agent_id=agent.id,
        source_ref=f"galaris://task/{uuid4()}",
        source_fingerprint="e" * 64,
        allowed_evidence_refs={"tool:0:check"},
        evidence_weight=0.8,
        decision=decision,
    )
    second = await learning_service.apply_learning_decision(
        agent_id=agent.id,
        source_ref=f"galaris://task/{uuid4()}",
        source_fingerprint="e" * 64,
        allowed_evidence_refs={"tool:0:check"},
        evidence_weight=0.8,
        decision=decision,
    )

    assert first.changed == 1
    assert second.changed == 0
    records = await learning_service.list_learning_context(agent.id)
    assert len(records) == 1
    assert records[0].evidence_count == 1
