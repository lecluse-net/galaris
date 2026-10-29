"""Evidence-based learning through the canonical personal package boundary."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select

from app.agent import Agent
from core.database import get_db
from core.params import runtime_settings
from core.util import complete_io

from . import interface, storage
from .contracts import SkillPackageCreate, SkillRevisionConflict, SkillScope
from .learning_contracts import (
    LearnedSkillApplyResult, LearnedSkillContext, LearnedSkillDecision,
)
from .learning_policy import eligible_learning_ids, is_injectable
from .models import Skill, SkillLearningEvidence


def reinforcement_score(positive_weight: float, negative_weight: float) -> float:
    positive = max(0.0, float(positive_weight))
    negative = max(0.0, float(negative_weight))
    return round((positive + 1.0) / (positive + negative + 2.0), 6)


def learning_mode() -> Literal["off", "observe", "learn"]:
    return runtime_settings.DREAM_SKILL_LEARNING_MODE


async def list_learning_context(agent_id: int, *, limit: int = 20) -> list[LearnedSkillContext]:
    """Read current personal files, including candidates and manually authored skills."""
    rows = (await get_db().scalars(select(Skill).where(
        Skill.owner_agent_id == agent_id,
    ).order_by(Skill.learning_score.desc(), Skill.id).limit(max(1, min(limit, 50))))).all()
    eligible = await eligible_learning_ids(agent_id)
    result: list[LearnedSkillContext] = []
    for row in rows:
        def read_source() -> tuple[str, str] | None:
            path = storage.resolve_file(row.code, "SKILL.md", owner_agent_id=agent_id)
            with path.open("rb") as stream:
                content = stream.read(64_001)
            if len(content) > 64_000:
                return None
            markdown = content.decode("utf-8")
            _, description = storage.metadata_from_markdown(markdown, expected_code=row.code)
            return markdown, description
        try:
            source = await complete_io(read_source)
        except (FileNotFoundError, OSError, ValueError):
            continue
        if source is None:
            continue
        markdown, description = source
        result.append(LearnedSkillContext(
            id=row.id, code=row.code, label=row.label,
            description=description, markdown=markdown,
            revision=row.revision, score=row.learning_score,
            evidence_count=row.learning_evidence_count,
            injectable=row.id in eligible if row.learning_key is not None else True,
        ))
    return result


async def learning_code_prefix(agent_id: int) -> str:
    code = await get_db().scalar(select(Agent.code).where(Agent.id == agent_id))
    if code is None:
        raise ValueError("Learning owner unavailable")
    return f"learned-{storage.slugify(str(code))}-"


async def apply_learning_decision(
    *, agent_id: int, source_ref: str, source_fingerprint: str,
    allowed_evidence_refs: set[str], evidence_weight: float,
    decision: LearnedSkillDecision,
) -> LearnedSkillApplyResult:
    """Create/revise real personal files and commit their evidence atomically.

    Ordinary package creation/editing enforces scope, quotas, revisions and disk recovery.
    The owner lock also serializes concurrent learning and ownership changes.
    """
    if not decision.operations:
        return LearnedSkillApplyResult(changed=0, refresh_required=False)
    db = get_db()
    if await interface.get_agent_scope(agent_id) == SkillScope.USAGE:
        raise PermissionError("Personal Skills management is required for Dream learning")
    prefix = await learning_code_prefix(agent_id)
    changed = 0
    touched: set[int] = set()
    for operation in decision.operations:
        refs = list(dict.fromkeys(operation.evidence_refs))
        if not refs or any(ref not in allowed_evidence_refs for ref in refs):
            continue
        await db.scalar(select(Agent.id).where(Agent.id == agent_id).with_for_update())
        if operation.action == "CREATE":
            code = storage.validate_code(operation.code)
            if not code.startswith(prefix) or len(code) <= len(prefix):
                raise ValueError("Invalid personal learning code prefix")
            target = await db.scalar(select(Skill).where(
                Skill.owner_agent_id == agent_id, Skill.learning_origin_code == code,
            ).with_for_update().execution_options(include_historized=True))
            if target is None:
                target = await db.scalar(select(Skill).where(
                Skill.owner_agent_id == agent_id, Skill.code == code,
                ).with_for_update().execution_options(include_historized=True))
            if target is not None and target.deleted_at is not None:
                continue
        else:
            identity = operation.target_skill_id
            target = await db.scalar(select(Skill).where(
                Skill.owner_agent_id == agent_id,
                Skill.learning_key == identity if isinstance(identity, UUID) else Skill.id == identity,
            ).with_for_update())
            # Deleted, transferred or published packages must never be recreated by a late decision.
            if target is None:
                continue
        if target is not None:
            if target.id in touched or await db.scalar(select(SkillLearningEvidence.id).where(
                SkillLearningEvidence.skill_id == target.id,
                SkillLearningEvidence.source_fingerprint == source_fingerprint,
            )) is not None:
                continue
            # A fresh correction of the same Task can revise the text, but cannot count as
            # another independent confirming Task.
            independent = await db.scalar(select(SkillLearningEvidence.id).where(
                SkillLearningEvidence.skill_id == target.id,
                SkillLearningEvidence.source_ref == source_ref,
                SkillLearningEvidence.polarity == "positive",
            )) is None
        else:
            independent = True
        action = "REINFORCE" if operation.action == "CREATE" and target is not None else operation.action
        if action == "REVISE" and (operation.expected_revision is None or target is None
                                  or target.revision != operation.expected_revision):
            continue
        if action in {"CREATE", "REVISE"}:
            storage.metadata_from_markdown(operation.markdown, expected_code=operation.code if target is None else target.code)
            if len(operation.markdown.encode("utf-8")) > 64_000:
                raise ValueError("Learned procedure exceeds 64 KiB")
            markdown = operation.markdown.strip() + "\n"
        else:
            assert target is not None
            markdown = await complete_io(storage.read_text, target.code, "SKILL.md", owner_agent_id=agent_id)

        def record_evidence(record: Skill) -> None:
            weight = max(0.1, min(float(evidence_weight), 2.0))
            negative = action == "WEAKEN"
            record.learning_positive_weight = (record.learning_positive_weight or 0.0) + (weight if independent and not negative else 0)
            record.learning_negative_weight = (record.learning_negative_weight or 0.0) + (weight if negative else 0)
            record.learning_evidence_count = (record.learning_evidence_count or 0) + int(independent and not negative)
            record.learning_score = reinforcement_score(record.learning_positive_weight, record.learning_negative_weight)
            record.learning_last_evidence_at = datetime.now(timezone.utc)
            db.add(SkillLearningEvidence(
                skill_id=record.id, source_ref=source_ref, source_fingerprint=source_fingerprint,
                operation=action, polarity="negative" if negative else "positive", weight=weight,
                confidence=operation.confidence, evidence_refs=refs, rationale=operation.rationale,
                instruction_digest=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            ))

        if target is None:
            def initialize(record: Skill) -> None:
                record.learning_key = uuid4()
                record_evidence(record)
            package = await interface.create_package(
                SkillPackageCreate(code=operation.code, label=operation.label, markdown=markdown),
                actor_agent_id=agent_id, _before_commit=initialize,
            )
            touched.add(package.id)
        elif action == "REVISE":
            try:
                await interface.mutate_file(target.id, "SKILL.md", actor_agent_id=agent_id,
                    operation="write", content=markdown.encode("utf-8"),
                    expected_revision=operation.expected_revision,
                    label=operation.label or None, _before_commit=record_evidence)
            except SkillRevisionConflict:
                continue
            touched.add(target.id)
        else:
            record_evidence(target)
            await db.flush()
            touched.add(target.id)
        changed += 1
    return LearnedSkillApplyResult(changed=changed, refresh_required=changed > 0)


__all__ = ["apply_learning_decision", "is_injectable", "learning_mode",
           "learning_code_prefix", "list_learning_context", "reinforcement_score"]
