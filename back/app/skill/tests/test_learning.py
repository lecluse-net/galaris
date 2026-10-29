"""Dream creates and evolves the same personal packages humans and agents manage."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.skill import interface, learning_service, personal_catalogue, storage
from app.skill.learning_contracts import LearnedSkillDecision, LearnedSkillOperation
from app.skill.models import Skill, SkillLearningEvidence
from app.skill.projection import build_skill_projection
from app.harness.skills import build_internal_skill_capabilities
from .test_personal_packages import agents, personal, set_scope


def operation(action, *, code=None, target=None, revision=None, body="Run the verified check."):
    return LearnedSkillOperation(
        action=action, code=code or "", label="Synthetic procedure" if code else "",
        target_skill_id=target, expected_revision=revision,
        markdown=personal(code, body).markdown if code and action in {"CREATE", "REVISE"} else "",
        evidence_refs=["tool:0:check"], rationale="Synthetic observed tool evidence.", confidence=0.9,
    )


async def apply(owner, op, fingerprint=None, task=None):
    return await learning_service.apply_learning_decision(
        agent_id=owner.id, source_ref=f"galaris://task/{task or uuid4()}",
        source_fingerprint=fingerprint or uuid4().hex * 2,
        allowed_evidence_refs={"tool:0:check"}, evidence_weight=0.8,
        decision=LearnedSkillDecision(operations=[op]),
    )


def test_learning_mode_exposes_only_the_effective_feature_state(monkeypatch):
    monkeypatch.setattr(learning_service.runtime_settings, "DREAM_SKILL_LEARNING_MODE", "observe")
    assert learning_service.learning_mode() == "observe"


@pytest.mark.asyncio
async def test_learning_creates_editable_personal_package_with_one_runtime_path(db, agents, monkeypatch):
    owner, other, _ = agents
    code = f"learned-{owner.code}-check"
    monkeypatch.setattr(learning_service.runtime_settings, "DREAM_SKILL_MIN_EVIDENCE", 3)
    monkeypatch.setattr(learning_service.runtime_settings, "DREAM_SKILL_ACTIVATION_SCORE", 0.75)
    assert (await apply(owner, operation("CREATE", code=code))).changed == 1
    candidate = (await learning_service.list_learning_context(owner.id))[0]
    package = await db.get(Skill, candidate.id)
    assert package.owner_agent_id == owner.id and package.creator_agent_id == owner.id
    catalogue, total = await personal_catalogue.list_page(agent_ids=[owner.id])
    assert total == 1 and catalogue[0].id == candidate.id
    assert catalogue[0].learning.evidence_count == 1
    assert not catalogue[0].learning.qualified
    assert storage.read_text(code, "SKILL.md", owner_agent_id=owner.id) == candidate.markdown
    assert not (await build_skill_projection(owner.id)).files
    assert not await interface.list_packages(actor_agent_id=other.id)
    for _ in range(2):
        await apply(owner, operation("REINFORCE", target=candidate.id))
    assert [p.id for p in await interface.personal_packages(owner.id)] == [candidate.id]
    snapshot = await build_skill_projection(owner.id)
    assert len(snapshot.files) == 1 and snapshot.files[0].package_id == candidate.id
    assert snapshot.files[0].owner_agent_id == owner.id
    assert not (storage.root() / ".learned").exists()
    capabilities = await build_internal_skill_capabilities(owner.id)
    assert len(capabilities) == 1 and capabilities[0].id == snapshot.files[0].skill_code
    assert not (await build_skill_projection(other.id)).files
    # The normal editor writes the canonical source that future executions read.
    updated = personal(code, "Human-reviewed procedure.").markdown
    await interface.mutate_file(package.id, "SKILL.md", actor_agent_id=owner.id,
        operation="write", content=updated.encode(), expected_revision=package.revision)
    assert (await learning_service.list_learning_context(owner.id))[0].markdown == updated
    assert (await build_skill_projection(owner.id)).files[0].source.read_text() == updated
    await apply(owner, operation("WEAKEN", target=package.id))
    assert not (await build_skill_projection(owner.id)).files
    assert len((await db.scalars(select(SkillLearningEvidence).where(
        SkillLearningEvidence.skill_id == package.id))).all()) == 4


@pytest.mark.asyncio
async def test_learning_replay_and_same_task_do_not_inflate_independent_evidence(db, agents):
    owner, _, _ = agents
    code = f"learned-{owner.code}-idempotent"
    op = operation("CREATE", code=code)
    task = uuid4()
    first = await apply(owner, op, "a" * 64, task)
    repeated = await apply(owner, op, "a" * 64, task)
    await apply(owner, op, "b" * 64, task)
    assert first.changed == 1 and repeated.changed == 0
    context = (await learning_service.list_learning_context(owner.id))[0]
    assert context.evidence_count == 1
    assert len((await db.scalars(select(Skill).where(Skill.owner_agent_id == owner.id))).all()) == 1


@pytest.mark.asyncio
async def test_late_revision_preserves_human_edits_and_manual_deactivation(db, agents):
    owner, _, _ = agents
    code = f"learned-{owner.code}-revision"
    await apply(owner, operation("CREATE", code=code))
    context = (await learning_service.list_learning_context(owner.id))[0]
    await interface.mutate_file(context.id, "SKILL.md", actor_agent_id=owner.id,
        operation="write", content=personal(code, "Human edit.").markdown.encode(), expected_revision=context.revision)
    late = await apply(owner, operation("REVISE", code=code, target=context.id, revision=context.revision))
    assert late.changed == 0
    assert "Human edit." in storage.read_text(code, "SKILL.md", owner_agent_id=owner.id)
    current = (await learning_service.list_learning_context(owner.id))[0]
    await interface.set_package_enabled(context.id, False, actor_agent_id=owner.id, expected_revision=current.revision)
    for _ in range(4):
        await apply(owner, operation("REINFORCE", target=context.id))
    assert not await interface.personal_packages(owner.id)
    await set_scope(owner.id, "usage")
    empty = await learning_service.apply_learning_decision(agent_id=owner.id,
        source_ref=f"galaris://task/{uuid4()}", source_fingerprint="f" * 64,
        allowed_evidence_refs=set(), evidence_weight=1, decision=LearnedSkillDecision())
    assert empty.changed == 0
    with pytest.raises(PermissionError):
        await apply(owner, operation("CREATE", code=f"learned-{owner.code}-forbidden"))
    with pytest.raises(FileNotFoundError):
        await interface.read_package_file(context.id, "SKILL.md", actor_agent_id=owner.id)


@pytest.mark.asyncio
async def test_failed_package_commit_keeps_neither_files_nor_evidence(db, agents, monkeypatch):
    owner, _, _ = agents
    owner_id = owner.id
    code = f"learned-{owner.code}-failure"
    async def fail():
        raise RuntimeError("Synthetic database commit failure")
    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError, match="Synthetic database"):
            await apply(owner, operation("CREATE", code=code))
    assert not storage.skill_dir(code, owner_agent_id=owner_id).exists()
    assert not (await db.scalars(select(Skill).where(Skill.owner_agent_id == owner_id))).all()
    assert not (await db.scalars(select(SkillLearningEvidence))).all()
