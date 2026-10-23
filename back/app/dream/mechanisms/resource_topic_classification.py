"""Classify independent documents and JSON Datasets with versioned checkpoints."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select

from app.dataset import facade as datasets
from app.llm import model_usages, profile_service
from app.document import facade as documents
from app.topic import TopicClassification, classify_topic as classify, service as topics
from core.database import get_db, get_db_session

from ..contracts import DreamClaim, DreamPrepared
from ..language import source_language
from ..models import DreamReceipt
from ..service import claim_retry, create_running_receipt
from .topic_classification import topic_classification_payload, topic_creation_mode
from .memory_extraction import safe_memory_text


class ResourceTopicClassificationMechanism:
    def __init__(
        self,
        kind: str,
        *,
        count: Callable[[Select[tuple[str]]], Awaitable[int]],
        claim: Callable[[Select[tuple[str]]], Awaitable[str | None]],
        source: Callable[[str], Awaitable[tuple[str, int | None, str | None] | None]],
        current: Callable[[str], Awaitable[bool]],
        assign: Callable[[str, UUID], Awaitable[bool]],
    ) -> None:
        self.kind = kind
        self.key = f"topic.classify_{kind}"
        self._count, self._claim, self._source, self._assign = count, claim, source, assign
        self._current = current

    def _handled(self) -> Select[tuple[str]]:
        return select(DreamReceipt.subject_id).where(
            DreamReceipt.mechanism_key == self.key,
            DreamReceipt.subject_kind == self.kind,
        )

    async def is_available(self) -> bool:
        async with get_db_session():
            return await profile_service.has_any_profile_value(model_usages.DREAM)

    async def count_pending(self) -> int:
        async with get_db_session():
            return await self._count(self._handled())

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        async with get_db_session():
            identity = await self._claim(self._handled())
            if identity is None:
                return None
            claim = create_running_receipt(
                mechanism_key=self.key, subject_kind=self.kind, subject_id=identity
            )
            await get_db().flush()
            return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        async with get_db_session():
            source = await self._source(claim.subject_id)
            if source is None:
                return DreamPrepared(payload={"stale": True})
            activity, agent_id, language_value = source
            activity = safe_memory_text(activity)
            language = source_language(language_value)
            candidates = await topics.list_candidates(activity=activity, limit=100)
            decision, cost = await classify(
                activity=activity,
                candidates=candidates,
                task_id=None,
                agent_id=agent_id,
                language=language,
            )
            decision, _ = await topics.prefer_reuse(decision)
            return DreamPrepared(
                payload=topic_classification_payload(
                    decision, candidates, language=language, creation_mode=topic_creation_mode()
                ),
                cost=cost,
            )

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        if payload.get("stale"):
            return 0
        decision = TopicClassification.model_validate(payload["decision"])
        # Resources have no conversation in which to ask for creation approval.
        # Propose/forbid therefore permit reuse only; auto permits public creation.
        if decision.action == "create" and payload.get("creation_mode") != "auto":
            return 0
        async with get_db_session():
            if not await self._current(claim.subject_id):
                return 0
            allowed = {UUID(str(value)) for value in payload.get("candidate_ids", [])}
            topic = await topics.resolve_classification(
                decision,
                allowed_topic_ids=allowed,
                language=source_language(payload.get("language")),
            )
            # Serialize against Topic deletion/merging before changing the resource.
            if not await topics.lock_for_resource_assignment(topic.id):
                return 0
            assigned = await self._assign(claim.subject_id, topic.id)
            if not assigned:
                await get_db().rollback()
            return int(assigned)


document_topic_classification_mechanism = ResourceTopicClassificationMechanism(
    "document",
    count=documents.count_pending_topic_documents,
    claim=documents.claim_topic_document,
    source=documents.topic_document_source,
    current=documents.topic_document_is_current,
    assign=documents.assign_document_topic,
)
dataset_topic_classification_mechanism = ResourceTopicClassificationMechanism(
    "dataset",
    count=datasets.count_pending_topic_datasets,
    claim=datasets.claim_topic_dataset,
    source=datasets.topic_dataset_source,
    current=datasets.topic_dataset_is_current,
    assign=datasets.assign_dataset_topic,
)
