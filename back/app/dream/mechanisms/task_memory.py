"""Extract durable memories from one classified terminal Task."""

from __future__ import annotations

from app.llm import model_usages

from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.llm import llm_service
from app.memory import MemoryType, search_memory_detailed
from app.task import ConversationFollowup, Task, TaskStatus, get_conversation_followup
from app.topic import Topic, service as topic_service
from core.database import get_db, get_db_session
from core.params import runtime_settings

from ..contracts import (
    DreamClaim,
    DreamPrepared,
    MemoryExtractionDecision,
    MemoryExtractionInput,
    MemoryExtractionMessage,
    MemoryExtractionPrepared,
)
from ..language import language_metadata, output_language_instruction, task_language
from ..models import DreamReceipt
from ..service import (
    claim_retry,
    claim_unverified_memory_application,
    create_running_receipt,
    replace_prepared_payload,
    unverified_memory_application,
)
from .memory_extraction import (
    MAX_RANKED_MEMORIES,
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    apply_memory_extraction,
    existing_memories_from_hits,
    memory_extraction_prepared_from_payload,
    memory_extraction_system_prompt,
    memory_extraction_unavailable,
    run_memory_extraction,
    safe_memory_text,
)


_MAX_SOURCE_CHARS = 20_000
_MAX_FOLLOWUP_CHARS = 4_000
_MAX_CONTACT_CHARS = 1_000
NOVELTY_MEMORY_TYPES: list[MemoryType] = [
    "core",
    "working",
    "episodic",
    "semantic",
    "procedural",
    "social",
]


def _eligible_task_predicates() -> tuple[ColumnElement[bool], ...]:
    """Require a Topic whose classification receipt is no longer active."""

    topic_classification_active = exists(
        select(DreamReceipt.id).where(
            DreamReceipt.mechanism_key == "topic.classify_task",
            DreamReceipt.subject_kind == "task",
            DreamReceipt.subject_id == cast(Task.id, String),
            DreamReceipt.status.in_(("running", "retry")),
        )
    )
    return (
        Task.status == TaskStatus.SUCCESS,
        Task.agent_id.is_not(None),
        Task.topic_id.is_not(None),
        or_(
            Task.messenger_connection_id.is_(None),
            Task.ai.is_(True),
            Task.contact_memory_item_id.is_not(None),
        ),
        Task.parent_id.is_(None),
        Task.goal_id.is_(None),
        Task.data["memory_capture"].as_boolean().is_not(False),
        or_(Task.message_platform.is_(None), ~Task.message_platform.startswith("voice:")),
        ~topic_classification_active,
    )


def _task_contact(task: Task) -> str:
    data = task.data if isinstance(task.data, dict) else {}
    if bool(data.get("sender_is_ai")):
        return ""
    user_id = str(
        data.get("sender.user_id") or data.get("sender.id") or data.get("user_id") or ""
    ).strip()
    platform = str(task.message_platform or "").strip()
    if not user_id or not platform:
        return ""
    display_name = str(
        data.get("sender.display_name") or data.get("sender.nickname") or ""
    ).strip()
    values = [
        f"messaging_id: {safe_memory_text(platform)}",
        f"user_id: {safe_memory_text(user_id)}",
    ]
    if display_name:
        values.append(f"display_name: {safe_memory_text(display_name)}")
    return "\n".join(values)[:_MAX_CONTACT_CHARS]


def _task_human_name(task: Task) -> str:
    data = task.data if isinstance(task.data, dict) else {}
    return str(
        data.get("sender.display_name")
        or data.get("sender.nickname")
        or data.get("sender_display_name")
        or data.get("sender.user_id")
        or data.get("sender.id")
        or data.get("sender_external_id")
        or "Participant"
    ).strip()


def _task_prompt(  # pyright: ignore[reportUnusedFunction]
    task: Task, followup: ConversationFollowup | None = None
) -> str:
    """Keep the historical helper as a readable source preview and test contract."""

    result = task.get_execution_result()
    contact = _task_contact(task)
    sections = [
        f"Task status: {task.status.value}",
        *([f"Current human contact (exact identity):\n{contact}"] if contact else []),
        f"Label:\n{safe_memory_text(task.label)}",
        f"Objective:\n{safe_memory_text(task.objective)}",
        f"Outcome:\n{safe_memory_text(result.result if result is not None else '')}",
        f"Feedback:\n{safe_memory_text(task.feedback)}",
        f"Recorded error:\n{safe_memory_text(task.last_error)}",
    ]
    prompt = "\n\n".join(section for section in sections if not section.endswith(":\n"))
    if followup is None or not followup.objective:
        return prompt[:_MAX_SOURCE_CHARS]
    followup_section = (
        "\n\nFollowing task objective in the same conversation "
        "(context about the current task only):\n"
        f"{safe_memory_text(followup.objective)[:_MAX_FOLLOWUP_CHARS]}"
    )
    return f"{prompt[: max(0, _MAX_SOURCE_CHARS - len(followup_section))]}{followup_section}"


def _novelty_query(task: Task, followup: ConversationFollowup | None = None) -> str:
    result = task.get_execution_result()
    values = (result.result if result is not None else "", task.objective, task.label)
    query = " ".join(safe_memory_text(value) for value in values if value)
    if followup is not None and followup.objective:
        query = f"{query} {safe_memory_text(followup.objective)}"
    contact = _task_contact(task)
    return f"{contact} {query}".strip()[:4_000]


def build_task_extraction_input(
    task: Task,
    *,
    followup: ConversationFollowup | None,
    topic: Topic,
) -> MemoryExtractionInput:
    result = task.get_execution_result()
    human_source = safe_memory_text(task.objective or task.label)
    current = [
        MemoryExtractionMessage(
            speaker_name=_task_human_name(task),
            speaker_kind="human",
            text=human_source,
        )
    ]
    outcome = safe_memory_text(result.result if result is not None else "")
    if outcome:
        current.append(
            MemoryExtractionMessage(
                speaker_name=(f"Agent {task.agent_id}" if task.agent_id else "Agent"),
                speaker_kind="AI",
                text=outcome[:8_000],
            )
        )
    return MemoryExtractionInput(
        source_kind="task",
        topic={
            "id": str(topic.id),
            "title": topic.title,
            "description": topic.description,
            "keywords": list(topic.keywords),
        },
        current=current,
        task_trace={
            "status": task.status.value,
            "label": safe_memory_text(task.label),
            "objective": safe_memory_text(task.objective),
            "outcome": outcome,
            "feedback": safe_memory_text(task.feedback),
            "recorded_error": safe_memory_text(task.last_error),
            "contact": _task_contact(task),
            "following_objective": (
                safe_memory_text(followup.objective)[:_MAX_FOLLOWUP_CHARS]
                if followup is not None
                else ""
            ),
        },
    )


class TaskMemoryMechanism:
    key = "memory.extract_task"

    async def is_available(self) -> bool:
        if not runtime_settings.MEMORY_CAPTURE_ENABLED:
            return False
        async with get_db_session():
            from app.llm import profile_service

            return await profile_service.has_any_profile_value(model_usages.DREAM)

    async def count_pending(self) -> int:
        async with get_db_session():
            already_scanned = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "task",
                    DreamReceipt.subject_id == cast(Task.id, String),
                )
            )
            needs_application_proof = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "task",
                    DreamReceipt.subject_id == cast(Task.id, String),
                    unverified_memory_application(),
                )
            )
            return int(
                await get_db().scalar(
                    select(func.count(Task.id)).where(
                        *_eligible_task_predicates(),
                        or_(~already_scanned, needs_application_proof),
                    )
                )
                or 0
            )

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(
            self.key,
            eligibility=exists(
                select(Task.id).where(
                    cast(Task.id, String) == DreamReceipt.subject_id,
                    *_eligible_task_predicates(),
                )
            ),
        )
        if retry is not None:
            return retry
        unverified = await claim_unverified_memory_application(
            self.key,
            eligibility=exists(
                select(Task.id).where(
                    cast(Task.id, String) == DreamReceipt.subject_id,
                    *_eligible_task_predicates(),
                )
            ),
        )
        if unverified is not None:
            return unverified
        async with get_db_session():
            already_scanned = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "task",
                    DreamReceipt.subject_id == cast(Task.id, String),
                )
            )
            task = await get_db().scalar(
                select(Task)
                .where(*_eligible_task_predicates(), ~already_scanned)
                .order_by(Task.created_at, Task.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if task is None:
                return None
            claim = create_running_receipt(
                mechanism_key=self.key,
                subject_kind="task",
                subject_id=str(task.id),
            )
            await get_db().flush()
            return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        task_id = UUID(claim.subject_id)
        async with get_db_session():
            task = await get_db().get(Task, task_id)
            if task is None or task.agent_id is None or task.topic_id is None:
                return DreamPrepared(
                    payload=MemoryExtractionPrepared(
                        decision=MemoryExtractionDecision()
                    ).model_dump(mode="json")
                )
            topic = await get_db().get(Topic, task.topic_id)
            if topic is None:
                return DreamPrepared(
                    payload=MemoryExtractionPrepared(
                        decision=MemoryExtractionDecision()
                    ).model_dump(mode="json")
                )
            if topic.memory_item_id is None:
                await topic_service.project_memory(topic)
            followup = await get_conversation_followup(task)
            extraction_input = build_task_extraction_input(
                task, followup=followup, topic=topic
            )
            query = _novelty_query(task, followup)
            agent_id = task.agent_id
            language = task_language(task)
            contact_item_id = task.contact_memory_item_id
            topic_item_id = topic.memory_item_id

        async with get_db_session():
            recalled = await search_memory_detailed(
                query,
                agent_id=agent_id,
                limit=MAX_RANKED_MEMORIES,
                memory_types=NOVELTY_MEMORY_TYPES,
                task_id=task_id,
                topic_item_id=(topic_item_id if contact_item_id is not None else None),
                contact_item_id=contact_item_id,
                record_llm_access=False,
                telemetry_kind="dream",
            )
            extraction_input = extraction_input.model_copy(
                update={
                    "existing_memories": existing_memories_from_hits(
                        recalled.hits,
                        owner_agent_id=agent_id,
                        source_text=query,
                    )
                }
            )
            llm = await llm_service.get_profile_llm_for_agent_id(
                model_usages.DREAM, agent_id
            )
            if llm is None:
                raise RuntimeError("No Dream model is configured for this agent profile.")
            language_instruction = output_language_instruction(
                language,
                fields="memory titles, contents, and keywords",
            )
            prepared, cost = await run_memory_extraction(
                llm=llm,
                input_data=extraction_input,
                system_prompt=await memory_extraction_system_prompt(),
                task_id=task_id,
                agent_id=agent_id,
                language_instruction=language_instruction,
            )
            return DreamPrepared(payload=prepared.model_dump(mode="json"), cost=cost)

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        prepared = memory_extraction_prepared_from_payload(payload)
        task_id = UUID(claim.subject_id)
        async with get_db_session():
            task = await get_db().get(Task, task_id)
            if task is None or task.agent_id is None or task.topic_id is None:
                return memory_extraction_unavailable(
                    prepared,
                    reason="Task memory source is no longer available",
                )
            if (
                task.messenger_connection_id is not None
                and not task.ai
                and task.contact_memory_item_id is None
            ):
                return memory_extraction_unavailable(
                    prepared,
                    reason="Task contact scope is no longer available",
                )
            topic = await get_db().get(Topic, task.topic_id)
            if topic is None:
                return memory_extraction_unavailable(
                    prepared,
                    reason="Task Topic is no longer available",
                )
            if topic.memory_item_id is None:
                await topic_service.project_memory(topic)
            result = task.get_execution_result()
            excerpt = "\n\n".join(
                value
                for value in (
                    safe_memory_text(task.objective),
                    safe_memory_text(result.result if result is not None else ""),
                )
                if value
            )[:8_000]
            metadata: dict[str, Any] = {
                "dream_receipt_id": str(claim.receipt_id),
                "dream_mechanism": self.key,
                **language_metadata(task_language(task)),
            }
            if task.contact_memory_item_id is not None:
                metadata.update(
                    {
                        "scope_mode": "topic_contact",
                        "contact_item_id": str(task.contact_memory_item_id),
                        "topic_item_id": str(topic.memory_item_id),
                    }
                )
            application = await apply_memory_extraction(
                prepared,
                agent_id=task.agent_id,
                source_kind="task",
                source_ref=f"task:{task.id}",
                source_excerpt=excerpt,
                memory_created_at=task.created_at,
                metadata=metadata,
                contact_item_id=task.contact_memory_item_id,
                topic_item_id=topic.memory_item_id,
                idempotency_prefix=f"dream:{self.key}:{task.id}",
            )
            updated = prepared.model_copy(update={"application": application})
            await replace_prepared_payload(claim, updated.model_dump(mode="json"))
            return len(application.operations)


task_memory_mechanism = TaskMemoryMechanism()


__all__ = [
    "MEMORY_EXTRACTION_SYSTEM_PROMPT",
    "NOVELTY_MEMORY_TYPES",
    "TaskMemoryMechanism",
    "build_task_extraction_input",
    "safe_memory_text",
    "task_memory_mechanism",
]
