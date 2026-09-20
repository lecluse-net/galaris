"""Extract durable memories from classified text-conversation rounds."""

from __future__ import annotations

from app.llm import model_usages

from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, cast as sql_cast, exists, func, or_, select

from app.conversation import (
    ConversationRound,
    ConversationRoundMessage,
)
from app.connection import Connection
from app.llm import llm_service
from app.memory import search_memory_detailed
from app.messenger import Message, MessengerUser, Room
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
from ..language import language_metadata, output_language_instruction, source_language
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
    apply_memory_extraction,
    existing_memories_from_hits,
    memory_extraction_prepared_from_payload,
    memory_extraction_system_prompt,
    memory_extraction_unavailable,
    run_memory_extraction,
    safe_memory_text,
)
from .task_memory import NOVELTY_MEMORY_TYPES


def _eligible_round_predicates() -> tuple[Any, ...]:
    linked_input = exists(
        select(ConversationRoundMessage.message_id)
        .join(Message, Message.id == ConversationRoundMessage.message_id)
        .where(
            ConversationRoundMessage.round_id == ConversationRound.id,
            ConversationRoundMessage.role == "input",
            func.length(func.trim(Message.text)) > 0,
        )
    )
    return (
        ConversationRound.status.in_(("SUCCEEDED", "ERROR_RESOLVED", "COMPLETED")),
        ConversationRound.topic_id.is_not(None),
        ConversationRound.contact_memory_item_id.is_not(None),
        linked_input,
    )


def _sender_name(
    row: Message,
    display_name: str | None,
    external_id: str | None,
    *,
    is_agent: bool = False,
) -> str:
    metadata = row.metadata_
    if is_agent:
        return str(
            metadata.get("sender_display_name")
            or metadata.get("sender_id")
            or "Agent"
        ).strip()
    return str(
        display_name
        or external_id
        or metadata.get("sender_display_name")
        or metadata.get("sender_id")
        or row.user_id
        or "Participant"
    ).strip()


def _journal_message(
    row: Message,
    *,
    sender_display_name: str | None,
    sender_external_id: str | None,
) -> MemoryExtractionMessage | None:
    text = safe_memory_text(row.text)
    if not text:
        return None
    is_agent = row.direction == "outbound"
    return MemoryExtractionMessage(
        speaker_name=_sender_name(
            row,
            sender_display_name,
            sender_external_id,
            is_agent=is_agent,
        ),
        speaker_kind="AI" if is_agent else "human",
        text=text[:8_000],
    )


async def _round_messages(
    round_: ConversationRound,
) -> tuple[list[MemoryExtractionMessage], list[MemoryExtractionMessage]]:
    linked_rows = (
        await get_db().execute(
            select(
                ConversationRoundMessage.role,
                Message,
                MessengerUser.display_name,
                MessengerUser.external_id,
            )
            .join(Message, Message.id == ConversationRoundMessage.message_id)
            .outerjoin(MessengerUser, MessengerUser.id == Message.messenger_user_id)
            .where(ConversationRoundMessage.round_id == round_.id)
            .order_by(
                ConversationRoundMessage.response_sequence.nullsfirst(),
                ConversationRoundMessage.sequence,
                Message.id,
            )
        )
    ).all()
    current = [
        MemoryExtractionMessage(
            speaker_name=_sender_name(
                row,
                display_name,
                external_id,
                is_agent=role == "output",
            ),
            speaker_kind="AI" if role == "output" else "human",
            text=text[:8_000],
        )
        for role, row, display_name, external_id in linked_rows
        if (text := safe_memory_text(row.text))
    ]
    history: list[MemoryExtractionMessage] = []
    if current:
        if round_.voice_session_id is not None and round_.sequence is not None:
            previous_ids = list(
                (
                    await get_db().scalars(
                        select(ConversationRound.id)
                        .where(
                            ConversationRound.voice_session_id == round_.voice_session_id,
                            ConversationRound.sequence < round_.sequence,
                            ConversationRound.status == "COMPLETED",
                        )
                        .order_by(ConversationRound.sequence.desc())
                        .limit(3)
                    )
                ).all()
            )
            if previous_ids:
                previous_rows = (
                    await get_db().execute(
                        select(
                            ConversationRoundMessage.role,
                            Message,
                            MessengerUser.display_name,
                            MessengerUser.external_id,
                        )
                        .join(Message, Message.id == ConversationRoundMessage.message_id)
                        .outerjoin(
                            MessengerUser,
                            MessengerUser.id == Message.messenger_user_id,
                        )
                        .where(
                            ConversationRoundMessage.round_id.in_(
                                list(reversed(previous_ids))
                            )
                        )
                        .order_by(Message.created_at, Message.id)
                    )
                ).all()
                history = [
                    MemoryExtractionMessage(
                        speaker_name=_sender_name(
                            row,
                            display_name,
                            external_id,
                            is_agent=role == "output",
                        ),
                        speaker_kind="AI" if role == "output" else "human",
                        text=text[:8_000],
                    )
                    for role, row, display_name, external_id in previous_rows
                    if (text := safe_memory_text(row.text))
                ][-5:]
        else:
            inputs = [row for role, row, _name, _id in linked_rows if role == "input"]
            if inputs:
                first = inputs[0]
                rows_desc = list(
                    (
                        await get_db().execute(
                            select(
                                Message,
                                MessengerUser.display_name,
                                MessengerUser.external_id,
                            )
                            .outerjoin(
                                MessengerUser,
                                MessengerUser.id == Message.messenger_user_id,
                            )
                            .where(
                                Message.messenger_room_id == round_.room_id,
                                or_(
                                    Message.created_at < first.created_at,
                                    and_(
                                        Message.created_at == first.created_at,
                                        Message.id < first.id,
                                    ),
                                ),
                                func.length(func.trim(Message.text)) > 0,
                            )
                            .order_by(Message.created_at.desc(), Message.id.desc())
                            .limit(5)
                        )
                    ).all()
                )
                history = [
                    message
                    for row, display_name, external_id in reversed(rows_desc)
                    if (
                        message := _journal_message(
                            row,
                            sender_display_name=display_name,
                            sender_external_id=external_id,
                        )
                    ) is not None
                ][-5:]
    return history, current


async def build_conversation_extraction_input(
    round_: ConversationRound,
    topic: Topic,
) -> MemoryExtractionInput:
    history, current = await _round_messages(round_)
    return MemoryExtractionInput(
        source_kind="conversation_round",
        topic={
            "id": str(topic.id),
            "title": topic.title,
            "description": topic.description,
            "keywords": list(topic.keywords),
        },
        history=history,
        current=current,
    )


async def round_execution_context(
    round_: ConversationRound,
) -> tuple[int, str] | None:
    row = (
        await get_db().execute(
            select(Connection.agent_id)
            .join(Room, Room.connection_id == Connection.id)
            .where(Room.id == round_.room_id)
            .execution_options(include_historized=True)
        )
    ).one_or_none()
    if row is None:
        return None
    return int(row.agent_id), round_.language


class ConversationMemoryMechanism:
    key = "memory.extract_conversation_round"

    async def is_available(self) -> bool:
        if not runtime_settings.MEMORY_CAPTURE_ENABLED:
            return False
        async with get_db_session():
            from app.llm import profile_service

            return await profile_service.has_any_profile_value(model_usages.DREAM)

    async def count_pending(self) -> int:
        async with get_db_session():
            scanned = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "conversation_round",
                    DreamReceipt.subject_id == sql_cast(ConversationRound.id, String),
                )
            )
            needs_application_proof = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "conversation_round",
                    DreamReceipt.subject_id == sql_cast(ConversationRound.id, String),
                    unverified_memory_application(),
                )
            )
            return int(
                await get_db().scalar(
                    select(func.count(ConversationRound.id)).where(
                        *_eligible_round_predicates(),
                        or_(~scanned, needs_application_proof),
                    )
                )
                or 0
            )

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(
            self.key,
            eligibility=exists(
                select(ConversationRound.id).where(
                    sql_cast(ConversationRound.id, String) == DreamReceipt.subject_id,
                    *_eligible_round_predicates(),
                )
            ),
        )
        if retry is not None:
            return retry
        unverified = await claim_unverified_memory_application(
            self.key,
            eligibility=exists(
                select(ConversationRound.id).where(
                    sql_cast(ConversationRound.id, String) == DreamReceipt.subject_id,
                    *_eligible_round_predicates(),
                )
            ),
        )
        if unverified is not None:
            return unverified
        async with get_db_session():
            scanned = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "conversation_round",
                    DreamReceipt.subject_id == sql_cast(ConversationRound.id, String),
                )
            )
            round_ = await get_db().scalar(
                select(ConversationRound)
                .where(*_eligible_round_predicates(), ~scanned)
                .order_by(ConversationRound.created_at, ConversationRound.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if round_ is None:
                return None
            claim = create_running_receipt(
                mechanism_key=self.key,
                subject_kind="conversation_round",
                subject_id=str(round_.id),
            )
            await get_db().flush()
            return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        round_id = UUID(claim.subject_id)
        async with get_db_session():
            round_ = await get_db().get(ConversationRound, round_id)
            if round_ is None or round_.topic_id is None:
                return DreamPrepared(
                    payload=MemoryExtractionPrepared(
                        decision=MemoryExtractionDecision()
                    ).model_dump(mode="json")
                )
            context = await round_execution_context(round_)
            topic = await get_db().get(Topic, round_.topic_id)
            if context is None or topic is None or round_.contact_memory_item_id is None:
                return DreamPrepared(
                    payload=MemoryExtractionPrepared(
                        decision=MemoryExtractionDecision()
                    ).model_dump(mode="json")
                )
            agent_id, raw_language = context
            if topic.memory_item_id is None:
                await topic_service.project_memory(topic)
            extraction_input = await build_conversation_extraction_input(
                round_, topic
            )
            current = extraction_input.current
            if not any(message.speaker_kind == "human" for message in current):
                return DreamPrepared(
                    payload=MemoryExtractionPrepared(
                        decision=MemoryExtractionDecision()
                    ).model_dump(mode="json")
                )
            language = source_language(raw_language)
            contact_item_id = round_.contact_memory_item_id
            topic_item_id = topic.memory_item_id
            query = " ".join(message.text for message in current)[:4_000]

        async with get_db_session():
            recalled = await search_memory_detailed(
                query,
                agent_id=agent_id,
                limit=MAX_RANKED_MEMORIES,
                memory_types=NOVELTY_MEMORY_TYPES,
                topic_item_id=topic_item_id,
                contact_item_id=contact_item_id,
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
                task_id=None,
                agent_id=agent_id,
                language_instruction=language_instruction,
            )
            return DreamPrepared(payload=prepared.model_dump(mode="json"), cost=cost)

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        prepared = memory_extraction_prepared_from_payload(payload)
        round_id = UUID(claim.subject_id)
        async with get_db_session():
            round_ = await get_db().get(ConversationRound, round_id)
            if round_ is None or round_.topic_id is None:
                return memory_extraction_unavailable(
                    prepared,
                    reason="Conversation memory source is no longer available",
                )
            context = await round_execution_context(round_)
            topic = await get_db().get(Topic, round_.topic_id)
            if context is None or topic is None or round_.contact_memory_item_id is None:
                return memory_extraction_unavailable(
                    prepared,
                    reason="Conversation memory scope is no longer available",
                )
            agent_id, raw_language = context
            if topic.memory_item_id is None:
                await topic_service.project_memory(topic)
            _history, current = await _round_messages(round_)
            source_excerpt = "\n\n".join(
                f"{message.speaker_name}: {message.text}" for message in current
            )[:8_000]
            language = source_language(raw_language)
            metadata = {
                "dream_receipt_id": str(claim.receipt_id),
                "dream_mechanism": self.key,
                "scope_mode": "topic_contact",
                "contact_item_id": str(round_.contact_memory_item_id),
                "topic_item_id": str(topic.memory_item_id),
                **language_metadata(language),
            }
            application = await apply_memory_extraction(
                prepared,
                agent_id=agent_id,
                source_kind="conversation_round",
                source_ref=f"conversation_round:{round_.id}",
                source_excerpt=source_excerpt,
                memory_created_at=round_.finished_at or round_.created_at,
                metadata=metadata,
                contact_item_id=round_.contact_memory_item_id,
                topic_item_id=topic.memory_item_id,
                idempotency_prefix=f"dream:{self.key}:{round_.id}",
            )
            updated = prepared.model_copy(update={"application": application})
            await replace_prepared_payload(claim, updated.model_dump(mode="json"))
            return len(application.operations)


conversation_memory_mechanism = ConversationMemoryMechanism()


__all__ = [
    "ConversationMemoryMechanism",
    "build_conversation_extraction_input",
    "conversation_memory_mechanism",
    "round_execution_context",
]
