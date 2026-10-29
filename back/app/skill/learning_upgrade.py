"""Transfer legacy DB-owned procedures to canonical personal packages before contraction."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import SchemaTransitionSet

from . import storage
from .models import AgentSkill, Skill, SkillLearningEvidence


class _LegacySkill(BaseModel):
    id: UUID
    agent_id: int
    code: str
    label: str
    markdown: str
    revision: int
    positive_weight: float
    negative_weight: float
    evidence_count: int
    score: float
    suspended: bool
    last_evidence_at: datetime | None
    created_at: datetime
    created_by: int | None = None
    updated_at: datetime | None = None
    updated_by: int | None = None
    deleted_at: datetime | None = None
    deleted_by: int | None = None


def needs_personal_learning(delta: SchemaTransitionSet) -> bool:
    return "learned_skills" in delta.removed_tables


async def _legacy_tables(session: AsyncSession) -> tuple[Table, Table] | None:
    if await session.scalar(text("SELECT to_regclass('public.learned_skills')")) is None:
        return None
    def reflect(connection: Connection) -> tuple[Table, Table]:
        metadata = MetaData()
        return (
            Table("learned_skills", metadata, autoload_with=connection),
            Table("learned_skill_evidences", metadata, autoload_with=connection),
        )
    return await (await session.connection()).run_sync(reflect)


def _renamed_markdown(markdown: str, code: str) -> str:
    import yaml
    lines = markdown.splitlines()
    end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    metadata = yaml.safe_load("\n".join(lines[1:end]))
    metadata["name"] = code
    return "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + "\n".join(lines[end + 1:]) + "\n"


async def transfer_personal_learning(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    tables = await _legacy_tables(session)
    if tables is None:
        return
    legacy, evidence = tables
    offset = 0
    while True:
        rows = (await session.execute(select(legacy).order_by(legacy.c.id).offset(offset).limit(100))).mappings().all()
        if not rows:
            break
        for raw in rows:
            old = _LegacySkill.model_validate(dict(raw))
            target = await session.scalar(select(Skill).where(Skill.learning_key == old.id)
                                          .execution_options(include_historized=True))
            if target is None:
                # A deterministic suffix preserves both packages on an existing homonym.
                code = old.code
                if await session.scalar(select(Skill.id).where(
                    Skill.owner_agent_id == old.agent_id, Skill.code == code,
                ).execution_options(include_historized=True)) is not None:
                    code = f"{old.code[:62].rstrip('-')}-{old.id.hex}"
                markdown = old.markdown.strip() + "\n" if code == old.code else _renamed_markdown(old.markdown, code)
                target = Skill(
                    code=code, label=old.label, owner_agent_id=old.agent_id,
                    creator_agent_id=old.agent_id, revision=old.revision,
                    learning_key=old.id, learning_origin_code=old.code,
                    learning_positive_weight=old.positive_weight,
                    learning_negative_weight=old.negative_weight,
                    learning_evidence_count=old.evidence_count, learning_score=old.score,
                    learning_last_evidence_at=old.last_evidence_at,
                    created_at=old.created_at, created_by=old.created_by,
                    updated_at=old.updated_at, updated_by=old.updated_by,
                    deleted_at=old.deleted_at, deleted_by=old.deleted_by,
                )
                session.add(target)
                await session.flush()
                path = storage.skill_dir(code, owner_agent_id=old.agent_id)
                if path.exists():
                    if storage.read_text(code, "SKILL.md", owner_agent_id=old.agent_id) != markdown:
                        raise RuntimeError("Conflicting personal skill files; legacy sources preserved")
                else:
                    await storage.install_markdown(code, old.label, markdown, owner_agent_id=old.agent_id)
                session.add(AgentSkill(skill_id=target.id, agent_id=old.agent_id, active=not old.suspended))
            for item in (await session.execute(select(evidence).where(
                evidence.c.learned_skill_id == old.id,
            ))).mappings():
                if await session.get(SkillLearningEvidence, item["id"]) is None:
                    fields = dict(item)
                    fields.pop("learned_skill_id")
                    session.add(SkillLearningEvidence(skill_id=target.id, **fields))
            await session.flush()
        offset += len(rows)


async def personal_learning_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    tables = await _legacy_tables(session)
    if tables is None:
        return True
    legacy, evidence = tables
    for raw in (await session.execute(select(legacy))).mappings():
        old = _LegacySkill.model_validate(dict(raw))
        target = await session.scalar(select(Skill).where(Skill.learning_key == old.id)
                                      .execution_options(include_historized=True))
        if target is None or (
            target.owner_agent_id, target.label, target.revision, target.learning_origin_code,
            target.learning_positive_weight, target.learning_negative_weight,
            target.learning_evidence_count, target.learning_score, target.deleted_at,
        ) != (
            old.agent_id, old.label, old.revision, old.code, old.positive_weight, old.negative_weight,
            old.evidence_count, old.score, old.deleted_at,
        ):
            return False
        expected = old.markdown.strip() + "\n" if target.code == old.code else _renamed_markdown(old.markdown, target.code)
        try:
            if storage.read_text(target.code, "SKILL.md", owner_agent_id=old.agent_id) != expected:
                return False
        except (FileNotFoundError, ValueError):
            return False
        if await session.scalar(select(AgentSkill.active).where(
            AgentSkill.skill_id == target.id, AgentSkill.agent_id == old.agent_id,
        )) != (not old.suspended):
            return False
        for item in (await session.execute(select(evidence).where(evidence.c.learned_skill_id == old.id))).mappings():
            copied = await session.get(SkillLearningEvidence, item["id"])
            if copied is None or copied.skill_id != target.id or any(
                getattr(copied, key) != value for key, value in item.items() if key != "learned_skill_id"
            ):
                return False
    return True
