"""Persistence, scoring and injection policy for learned skills."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timezone
import hashlib
from typing import Literal, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.agent import Agent
from core.database import get_db
from core.params import runtime_settings

from . import storage
from .learning_contracts import (
    LearnedSkillApplyResult,
    LearnedSkillContext,
    LearnedSkillDecision,
    LearnedSkillOperation,
    refresh_learned_skill_runtime,
)
from .models import LearnedSkill, LearnedSkillEvidence


def reinforcement_score(positive_weight: float, negative_weight: float) -> float:
    """Return a Laplace-smoothed confidence in the reusable procedure."""

    positive = max(0.0, float(positive_weight))
    negative = max(0.0, float(negative_weight))
    return round((positive + 1.0) / (positive + negative + 2.0), 6)


def learning_mode() -> Literal["off", "observe", "learn"]:
    """Return the effective feature mode without exposing the Params domain."""

    return runtime_settings.DREAM_SKILL_LEARNING_MODE


def is_injectable(skill: LearnedSkill) -> bool:
    return (
        not skill.suspended
        and skill.evidence_count >= runtime_settings.DREAM_SKILL_MIN_EVIDENCE
        and skill.score >= runtime_settings.DREAM_SKILL_ACTIVATION_SCORE
    )


def _context(skill: LearnedSkill) -> LearnedSkillContext:
    return LearnedSkillContext(
        id=skill.id,
        code=skill.code,
        label=skill.label,
        description=skill.description,
        markdown=skill.markdown,
        revision=skill.revision,
        score=skill.score,
        evidence_count=skill.evidence_count,
        injectable=is_injectable(skill),
    )


async def list_learning_context(agent_id: int, *, limit: int = 20) -> list[LearnedSkillContext]:
    """Return bounded current procedures, including those still being reinforced."""

    rows = list(
        (
            await get_db().scalars(
                select(LearnedSkill)
                .where(LearnedSkill.agent_id == agent_id)
                .order_by(
                    LearnedSkill.suspended,
                    LearnedSkill.score.desc(),
                    LearnedSkill.updated_at.desc(),
                )
                .limit(max(1, min(limit, 50)))
            )
        ).all()
    )
    return [_context(row) for row in rows]


async def list_injectable(agent_id: int) -> list[LearnedSkill]:
    """Return only learned procedures crossing the configured evidence gate."""

    result = await get_db().scalars(
        select(LearnedSkill)
        .where(
            LearnedSkill.agent_id == agent_id,
            LearnedSkill.suspended.is_(False),
            LearnedSkill.evidence_count >= runtime_settings.DREAM_SKILL_MIN_EVIDENCE,
            LearnedSkill.score >= runtime_settings.DREAM_SKILL_ACTIVATION_SCORE,
        )
        .order_by(LearnedSkill.score.desc(), LearnedSkill.updated_at.desc())
        .limit(runtime_settings.DREAM_SKILL_MAX_ACTIVE)
    )
    return list(result.all())


async def _agent_code(agent_id: int) -> str:
    code = await get_db().scalar(select(Agent.code).where(Agent.id == agent_id))
    if code is None:
        raise ValueError(f"Agent introuvable : {agent_id}")
    return storage.slugify(str(code))


async def learning_code_prefix(agent_id: int) -> str:
    """Return the server-owned namespace for one agent's learned skills."""

    return f"learned-{await _agent_code(agent_id)}-"


def _validate_markdown(code: str, markdown: str) -> str:
    normalized = markdown.strip() + "\n"
    _name, description = storage.metadata_from_markdown(
        normalized,
        expected_code=code,
    )
    if len(normalized.encode("utf-8")) > 64_000:
        raise ValueError("Une compétence apprise ne peut pas dépasser 64 Kio")
    return description


def _digest(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


async def _locked_skill(agent_id: int, skill_id: UUID) -> LearnedSkill | None:
    return await get_db().scalar(
        select(LearnedSkill)
        .where(LearnedSkill.id == skill_id, LearnedSkill.agent_id == agent_id)
        .with_for_update()
    )


async def _target_for_operation(
    *,
    agent_id: int,
    agent_code: str,
    operation: LearnedSkillOperation,
) -> tuple[LearnedSkill, bool]:
    if operation.action != "CREATE":
        if operation.target_skill_id is None:
            raise ValueError(f"{operation.action} requires a learned skill target")
        target = await _locked_skill(agent_id, operation.target_skill_id)
        if target is None:
            raise ValueError(f"Learned skill target unavailable: {operation.target_skill_id}")
        return target, False

    code = storage.validate_code(operation.code)
    required_prefix = f"learned-{agent_code}-"
    if not code.startswith(required_prefix) or len(code) <= len(required_prefix):
        raise ValueError(f"Learned skill codes must start with {required_prefix}")
    label = operation.label.strip()
    if not label:
        raise ValueError("A learned skill requires a non-empty label")
    description = _validate_markdown(code, operation.markdown)
    existing = await get_db().scalar(
        select(LearnedSkill)
        .where(LearnedSkill.agent_id == agent_id, LearnedSkill.code == code)
        .with_for_update()
    )
    if existing is not None:
        return existing, False
    target = LearnedSkill(
        agent_id=agent_id,
        code=code,
        label=label,
        description=description,
        markdown=operation.markdown.strip() + "\n",
    )
    get_db().add(target)
    await get_db().flush()
    return target, True


async def _has_evidence(skill_id: UUID, fingerprint: str) -> bool:
    return (
        await get_db().scalar(
            select(LearnedSkillEvidence.id).where(
                LearnedSkillEvidence.learned_skill_id == skill_id,
                LearnedSkillEvidence.source_fingerprint == fingerprint,
            )
        )
        is not None
    )


async def apply_learning_decision(
    *,
    agent_id: int,
    source_ref: str,
    source_fingerprint: str,
    allowed_evidence_refs: set[str],
    evidence_weight: float,
    decision: LearnedSkillDecision,
) -> LearnedSkillApplyResult:
    """Apply one checkpointed decision idempotently in the current transaction."""

    agent_code = await _agent_code(agent_id)
    changed = 0
    refresh_required = False
    touched: set[UUID] = set()
    for operation in decision.operations:
        refs = list(dict.fromkeys(operation.evidence_refs))
        if not refs or any(ref not in allowed_evidence_refs for ref in refs):
            continue
        target, created = await _target_for_operation(
            agent_id=agent_id,
            agent_code=agent_code,
            operation=operation,
        )
        if target.id in touched or await _has_evidence(target.id, source_fingerprint):
            continue
        touched.add(target.id)
        was_injectable = is_injectable(target)

        effective_action = operation.action
        if created:
            effective_action = "CREATE"
        elif operation.action == "CREATE":
            effective_action = "REINFORCE"
        if effective_action == "REVISE":
            description = _validate_markdown(target.code, operation.markdown)
            target.markdown = operation.markdown.strip() + "\n"
            target.description = description
            if operation.label.strip():
                target.label = operation.label.strip()
            target.revision += 1

        weight = max(0.1, min(float(evidence_weight), 2.0))
        polarity = "negative" if effective_action == "WEAKEN" else "positive"
        if polarity == "negative":
            target.negative_weight += weight
        else:
            target.positive_weight += weight
        target.evidence_count += 1
        target.score = reinforcement_score(
            target.positive_weight,
            target.negative_weight,
        )
        target.last_evidence_at = datetime.now(timezone.utc)
        get_db().add(
            LearnedSkillEvidence(
                learned_skill_id=target.id,
                source_ref=source_ref[:300],
                source_fingerprint=source_fingerprint,
                operation=effective_action,
                polarity=polarity,
                weight=weight,
                confidence=operation.confidence,
                evidence_refs=refs,
                rationale=operation.rationale,
                instruction_digest=_digest(target.markdown),
            )
        )
        changed += 1
        now_injectable = is_injectable(target)
        refresh_required = refresh_required or (
            was_injectable != now_injectable
            or (effective_action == "REVISE" and now_injectable)
        )

    return LearnedSkillApplyResult(
        changed=changed,
        refresh_required=refresh_required,
    )


async def list_records(
    *,
    agent_id: int | None,
    page: int,
    page_size: int,
    agent_ids: Collection[int] | None = None,
) -> tuple[Sequence[LearnedSkill], int]:
    statement = select(LearnedSkill)
    count_statement = select(func.count(LearnedSkill.id))
    if agent_id is not None:
        statement = statement.where(LearnedSkill.agent_id == agent_id)
        count_statement = count_statement.where(LearnedSkill.agent_id == agent_id)
    if agent_ids is not None:
        statement = statement.where(LearnedSkill.agent_id.in_(agent_ids))
        count_statement = count_statement.where(LearnedSkill.agent_id.in_(agent_ids))
    total = int(await get_db().scalar(count_statement) or 0)
    rows = (
        await get_db().scalars(
            statement
            .order_by(LearnedSkill.updated_at.desc(), LearnedSkill.code)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return rows, total


async def get_record(skill_id: UUID) -> LearnedSkill | None:
    return await get_db().scalar(
        select(LearnedSkill)
        .options(selectinload(LearnedSkill.evidences))
        .where(LearnedSkill.id == skill_id)
    )


async def set_suspended(skill_id: UUID, suspended: bool) -> LearnedSkill | None:
    record = await get_record(skill_id)
    if record is None:
        return None
    was_injectable = is_injectable(record)
    record.suspended = suspended
    await get_db().commit()
    await get_db().refresh(record, attribute_names=["evidences"])
    if was_injectable != is_injectable(record):
        await refresh_learned_skill_runtime(record.agent_id)
    return record


__all__ = [
    "apply_learning_decision",
    "get_record",
    "is_injectable",
    "learning_mode",
    "learning_code_prefix",
    "list_injectable",
    "list_learning_context",
    "list_records",
    "reinforcement_score",
    "set_suspended",
]
