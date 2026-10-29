"""Eligibility of Dream-created personal packages, shared by all consumers."""

from sqlalchemy import select

from core.database import get_db
from core.params import runtime_settings

from .models import AgentSkill, Skill


def is_injectable(skill: Skill) -> bool:
    return (
        skill.learning_key is None
        or (
            skill.learning_evidence_count >= runtime_settings.DREAM_SKILL_MIN_EVIDENCE
            and skill.learning_score >= runtime_settings.DREAM_SKILL_ACTIVATION_SCORE
        )
    )


async def eligible_learning_ids(agent_id: int) -> frozenset[int]:
    rows = await get_db().scalars(
        select(Skill.id).join(AgentSkill).where(
            Skill.owner_agent_id == agent_id,
            Skill.learning_key.is_not(None),
            AgentSkill.agent_id == agent_id,
            AgentSkill.active.is_(True),
            Skill.learning_evidence_count >= runtime_settings.DREAM_SKILL_MIN_EVIDENCE,
            Skill.learning_score >= runtime_settings.DREAM_SKILL_ACTIVATION_SCORE,
        ).order_by(Skill.learning_score.desc(), Skill.id)
        .limit(runtime_settings.DREAM_SKILL_MAX_ACTIVE)
    )
    return frozenset(rows)
