"""Production dependencies for the side-effect-free sequential Topic detector."""

from __future__ import annotations

from app.llm import model_usages

from uuid import UUID, uuid4

from sqlalchemy import select

from app.llm import llm_service
from core.database import get_db

from .models import Topic
from .schemas import TopicCandidate, TopicClassification
from .sequential_detection import (
    PromptedTopicDetectionModel,
    TopicDetectionDependencies,
)
from . import service


class RuntimeTopicCatalog:
    """Read the live Topic catalogue while keeping preparation free of writes."""

    async def get_candidate(self, topic_id: UUID) -> TopicCandidate | None:
        topic = await get_db().scalar(
            Topic.histo_filter(select(Topic).where(Topic.id == topic_id))
        )
        if topic is None:
            return None
        return TopicCandidate(
            id=topic.id,
            title=topic.title,
            description=topic.description,
            keywords=topic.keywords,
        )

    async def list_candidates(self, *, activity: str) -> list[TopicCandidate]:
        return await service.list_candidates(activity=activity, limit=100)

    async def resolve(
        self,
        decision: TopicClassification,
        *,
        allowed_topic_ids: set[UUID],
    ) -> UUID:
        if decision.action == "reuse":
            if decision.topic_id not in allowed_topic_ids:
                raise ValueError("The selected Topic is outside the runtime catalogue.")
            assert decision.topic_id is not None
            return decision.topic_id
        return decision.topic_id or uuid4()


async def runtime_topic_detection_dependencies(
    *,
    task_id: UUID | None,
    agent_id: int | None,
) -> TopicDetectionDependencies:
    """Resolve the configured Dream model for one checkpointed detection call."""

    llm = await llm_service.get_profile_llm_for_agent_id(
        model_usages.DREAM, agent_id
    )
    if llm is None:
        raise RuntimeError("No Dream model is configured for this agent profile.")
    return TopicDetectionDependencies(
        catalog=RuntimeTopicCatalog(),
        model=PromptedTopicDetectionModel(
            llm,
            task_id=task_id,
            agent_id=agent_id,
            use_decision_profile=True,
        ),
    )


__all__ = ["RuntimeTopicCatalog", "runtime_topic_detection_dependencies"]
