"""Extract durable memories from classified text-conversation rounds."""

from __future__ import annotations

from app.llm import model_usages

from typing import Any, Literal
import hashlib
import json
import re
from uuid import UUID

from sqlalchemy import String, and_, case, cast as sql_cast, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.conversation import (
    ConversationRound,
    ConversationRoundMessage,
    ConversationTaskLink,
)
from app.connection import Connection
from app.llm import llm_service
from app.llm.facade import acquired_document_evidence, document_evidence_revision
from app.memory import search_memory_detailed
from app.messenger import Attachment, File, Message, MessengerUser, Room, hydrate_messages, conversation_audio_transcripts, attachment_resource_uri
from app.topic import Topic, service as topic_service
from core.database import get_db, get_db_session
from core.params import runtime_settings

from ..contracts import (
    DreamClaim,
    DreamPrepared,
    MemoryExtractionDecision,
    MemoryExtractionInput,
    MemoryExtractionMessage,
    MemoryExtractionEvidence,
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


class ConversationEvidenceUnavailable(ValueError):
    """A previously eligible source no longer has accessible evidence."""


def _round_subject() -> Any:
    """Media additions have their own receipt; legacy text identities stay valid."""
    from app.task.facade import memory_evidence_task_tree
    task_ids = memory_evidence_task_tree(select(ConversationTaskLink.task_id).where(
        ConversationTaskLink.round_id == ConversationRound.id).correlate(ConversationRound))
    file_ids = select(Attachment.file_id).join(ConversationRoundMessage, ConversationRoundMessage.message_id == Attachment.message_id).where(
        ConversationRoundMessage.round_id == ConversationRound.id, ConversationRoundMessage.role == "input",
    ).correlate(ConversationRound)
    agent_id = select(Connection.agent_id).join(Room, Room.connection_id == Connection.id).where(
        Room.id == ConversationRound.room_id,
    ).correlate(ConversationRound).scalar_subquery()
    document_revision = document_evidence_revision(task_ids, file_ids, agent_id)
    audio_revision = select(func.coalesce(func.string_agg(
        func.concat(Message.id, ":", Message.text, ":", sql_cast(Message.metadata_["conversation_audio_transcripts"], String)), aggregate_order_by(literal("|"), Message.id)), "")).join(
        ConversationRoundMessage, ConversationRoundMessage.message_id == Message.id,
    ).where(ConversationRoundMessage.round_id == ConversationRound.id,
        ConversationRoundMessage.role == "input",
        Message.metadata_["conversation_audio_transcripts"].is_not(None),
    ).correlate(ConversationRound).scalar_subquery()
    identity = sql_cast(ConversationRound.id, String)
    revision = func.concat(audio_revision, "|", document_revision)
    return case((or_(audio_revision != "", document_revision != ""), func.concat(identity, ":",
        func.encode(func.sha256(func.convert_to(revision, "UTF8")), "hex"))), else_=identity)


def _eligible_round_predicates() -> tuple[Any, ...]:
    attached = exists(select(Attachment.file_id).join(File, File.id == Attachment.file_id).where(
        Attachment.message_id == Message.id, File.deleted_at.is_(None),
    ))
    linked_input = exists(
        select(ConversationRoundMessage.message_id)
        .join(Message, Message.id == ConversationRoundMessage.message_id)
        .where(
            ConversationRoundMessage.round_id == ConversationRound.id,
            ConversationRoundMessage.role == "input",
            or_(func.length(func.trim(Message.text)) > 0, attached),
        )
    )
    return (
        exists(select(Room.id).join(Connection, Connection.id == Room.connection_id).where(
            Room.id == ConversationRound.room_id, Room.deleted_at.is_(None), Connection.active.is_(True))),
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
    is_output: bool | None = None,
) -> MemoryExtractionMessage | None:
    text = safe_memory_text(row.text)
    text_limit = 4_000 if row.files else 8_000
    evidence: list[MemoryExtractionEvidence] = []
    if text:
        evidence.append(MemoryExtractionEvidence(ref=f"{row.id}:written", kind="written", message_id=row.id,
            text=text[:text_limit], coverage={"complete": len(text) <= text_limit},
            version={"text_sha256": hashlib.sha256(row.text.encode()).hexdigest()}))
    transcripts = conversation_audio_transcripts(row.metadata_)
    sections = [text[:text_limit]] if text else []
    remaining = 8_000 - min(len(text), text_limit)
    for file in row.files[:20]:
        try:
            uri = attachment_resource_uri(row.tool_code, row.room_id or "", file.id)
        except ValueError:
            continue
        transcript = safe_memory_text(transcripts.get(str(file.id), "")) if file.kind == "audio" else ""
        evidence.append(MemoryExtractionEvidence(ref=f"{row.id}:{file.id}",
            kind="transcription" if transcript else "attachment", message_id=row.id, uri=uri,
            text=transcript[:remaining], coverage={"status": "acquired" if transcript else "not_analyzed",
                "complete": bool(transcript) and len(transcript) <= remaining},
            version={"attestation": "unknown", "text_sha256": hashlib.sha256(
                transcripts.get(str(file.id), "").encode()).hexdigest()}))
        if transcript:
            sections.append(f"[Audio transcript: {file.name}]\n{transcript[:remaining]}")
            remaining -= min(len(transcript), remaining)
    if not sections and evidence:
        sections.append("[Attachments available; no acquired text evidence.]")
    if not sections:
        return None
    is_agent = row.direction == "outbound" if is_output is None else is_output
    return MemoryExtractionMessage(
        speaker_name=_sender_name(
            row,
            sender_display_name,
            sender_external_id,
            is_agent=is_agent,
        ),
        speaker_kind="AI" if is_agent else "human",
        occurred_at=row.created_at,
        text="\n\n".join(sections)[:8_000],
        evidence=evidence,
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
    await _hydrate_attached_messages([row for _role, row, _name, _id in linked_rows])
    current = [message
        for role, row, display_name, external_id in linked_rows
        if (message := _journal_message(row, sender_display_name=display_name,
            sender_external_id=external_id, is_output=role == "output")) is not None
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
                await _hydrate_attached_messages([row for _role, row, _name, _id in previous_rows])
                history = [message
                    for role, row, display_name, external_id in previous_rows
                    if (message := _journal_message(row, sender_display_name=display_name,
                        sender_external_id=external_id, is_output=role == "output")) is not None
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
                                or_(func.length(func.trim(Message.text)) > 0,
                                    Message.metadata_["conversation_audio_transcripts"].is_not(None)),
                            )
                            .order_by(Message.created_at.desc(), Message.id.desc())
                            .limit(5)
                        )
                    ).all()
                )
                await _hydrate_attached_messages([row for row, _name, _id in rows_desc])
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


async def _hydrate_attached_messages(messages: list[Message]) -> None:
    if not messages:
        return
    attached = set(await get_db().scalars(select(Attachment.message_id).where(
        Attachment.message_id.in_([message.id for message in messages]),
    )))
    rows = [message for message in messages if message.id in attached]
    if rows:
        await hydrate_messages(rows)


async def build_conversation_extraction_input(
    round_: ConversationRound,
    topic: Topic,
) -> MemoryExtractionInput:
    history, current = await _round_messages(round_)
    if not current:
        raise ConversationEvidenceUnavailable("Conversation evidence is no longer available")
    context = await round_execution_context(round_)
    from app.task.facade import memory_evidence_task_tree
    task_ids = tuple(await get_db().scalars(memory_evidence_task_tree(select(ConversationTaskLink.task_id).where(
        ConversationTaskLink.round_id == round_.id,
    ))))
    uris = tuple({part.uri for message in current for part in message.evidence if part.uri})
    acquired = await acquired_document_evidence(context[0], task_ids, uris) if context else []
    for message in current:
        message_uris = {part.uri for part in message.evidence}
        terms = {term.casefold() for term in re.findall(r"\w{3,}", message.text)}
        for analysis in acquired:
            if analysis.uri not in message_uris:
                continue
            # Select from already acquired passages. Keep boundary evidence and
            # question matches rather than silently retaining only the first page.
            passages = analysis.passages
            ranked = sorted(enumerate(passages), key=lambda pair: (
                -sum(term in str(pair[1].get("text", "")).casefold() for term in terms), pair[0]))
            selected = {index for index, _passage in ranked[:2]}
            if passages:
                selected.update((0, len(passages) - 1))
            message_id = next(part.message_id for part in message.evidence if part.uri == analysis.uri)
            new_parts: list[tuple[Literal["document_extraction", "document_interpretation"], str, str]] = [("document_extraction", str(passages[index].get("locator") or index),
                str(passages[index].get("text") or "")) for index in sorted(selected)]
            if analysis.answer:
                new_parts.append(("document_interpretation", "answer", analysis.answer))
            for kind, locator, source_text in new_parts:
                if len(message.evidence) >= 64:
                    break
                remaining_evidence = 8_000 - sum(len(part.text) for part in message.evidence)
                text = safe_memory_text(source_text)[:min(1_600, remaining_evidence)]
                if not text:
                    continue
                part = MemoryExtractionEvidence(ref=f"{analysis.analysis_id}:{locator}",
                    kind=kind, message_id=message_id, uri=analysis.uri, text=text,
                    version=analysis.version, locator=locator,
                    coverage={**analysis.coverage, "passage_truncated": len(source_text) > len(text),
                        "selected_passages": len(selected), "available_passages": len(passages)})
                message.evidence.append(part)
                label = f"\n\n[{kind}; {locator}; {part.ref}]\n"
                remaining = 8_000 - len(message.text) - len(label)
                if remaining > 0:
                    message.text += label + text[:remaining]
    return MemoryExtractionInput(
        source_kind="conversation_round",
        source_at=round_.created_at,
        topic={
            "id": str(topic.id),
            "title": topic.title,
            "description": topic.description,
            "keywords": list(topic.keywords),
        },
        history=history,
        current=current,
    )


def _source_snapshot(extraction: MemoryExtractionInput, round_: ConversationRound, agent_id: int) -> dict[str, Any]:
    source = {"agent_id": agent_id, "topic_id": str(round_.topic_id),
        "contact_item_id": str(round_.contact_memory_item_id), "language": round_.language,
        "current": [message.model_dump(mode="json") for message in extraction.current]}
    return {"fingerprint": hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "agent_id": agent_id, "evidence": [part.model_dump(mode="json")
            for message in extraction.current for part in message.evidence if part.text and part.kind != "attachment"]}


async def round_execution_context(
    round_: ConversationRound,
) -> tuple[int, str] | None:
    row = (
        await get_db().execute(
            select(Connection.agent_id)
            .join(Room, Room.connection_id == Connection.id)
            .where(Room.id == round_.room_id)
            .where(Connection.active.is_(True), Room.deleted_at.is_(None))
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
                    DreamReceipt.subject_id == _round_subject(),
                )
            )
            needs_application_proof = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "conversation_round",
                    DreamReceipt.subject_id == _round_subject(),
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
                    _round_subject() == DreamReceipt.subject_id,
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
                    _round_subject() == DreamReceipt.subject_id,
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
                    DreamReceipt.subject_id == _round_subject(),
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
                subject_id=str(await get_db().scalar(select(_round_subject()).where(ConversationRound.id == round_.id))),
            )
            await get_db().flush()
            return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        round_id = UUID(claim.subject_id.split(":", maxsplit=1)[0])
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
            current_subject = await get_db().scalar(select(_round_subject()).where(ConversationRound.id == round_.id))
            if str(current_subject) != claim.subject_id:
                return DreamPrepared(payload=MemoryExtractionPrepared(decision=MemoryExtractionDecision()).model_dump(mode="json"))
            if topic.memory_item_id is None:
                await topic_service.project_memory(topic)
            try:
                extraction_input = await build_conversation_extraction_input(round_, topic)
            except ConversationEvidenceUnavailable:
                return DreamPrepared(payload=MemoryExtractionPrepared(decision=MemoryExtractionDecision()).model_dump(mode="json"))
            current = extraction_input.current
            if not any(message.speaker_kind == "human" and any(part.text for part in message.evidence) for message in current):
                return DreamPrepared(
                    payload=MemoryExtractionPrepared(
                        decision=MemoryExtractionDecision()
                    ).model_dump(mode="json")
                )
            language = source_language(raw_language)
            contact_item_id = round_.contact_memory_item_id
            topic_item_id = topic.memory_item_id
            query = " ".join(message.text for message in current)[:4_000]
            snapshot = _source_snapshot(extraction_input, round_, agent_id)

        async with get_db_session():
            recalled = await search_memory_detailed(
                query,
                agent_id=agent_id,
                limit=MAX_RANKED_MEMORIES,
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
            prepared = prepared.model_copy(update={"source_snapshot": snapshot})
            return DreamPrepared(payload=prepared.model_dump(mode="json"), cost=cost)

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        prepared = memory_extraction_prepared_from_payload(payload)
        round_id = UUID(claim.subject_id.split(":", maxsplit=1)[0])
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
            try:
                extraction = await build_conversation_extraction_input(round_, topic)
            except ConversationEvidenceUnavailable:
                return memory_extraction_unavailable(prepared, reason="Conversation memory evidence is no longer available")
            current = extraction.current
            snapshot = _source_snapshot(extraction, round_, agent_id)
            if prepared.source_snapshot is not None and prepared.source_snapshot["fingerprint"] != snapshot["fingerprint"]:
                return memory_extraction_unavailable(prepared, reason="Conversation memory evidence changed after preparation")
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
                "source_evidence": snapshot["evidence"],
                "evidence_validator": "conversation",
                **language_metadata(language),
            }
            application = await apply_memory_extraction(
                prepared,
                agent_id=agent_id,
                source_kind="conversation_round",
                source_ref=f"conversation_round:{claim.subject_id}",
                source_excerpt=source_excerpt,
                memory_created_at=round_.finished_at or round_.created_at,
                metadata=metadata,
                contact_item_id=round_.contact_memory_item_id,
                topic_item_id=topic.memory_item_id,
                idempotency_prefix=f"dream:{self.key}:{claim.subject_id}",
            )
            updated = prepared.model_copy(update={"application": application})
            await replace_prepared_payload(claim, updated.model_dump(mode="json"))
            return application.stored_count


conversation_memory_mechanism = ConversationMemoryMechanism()


__all__ = [
    "ConversationMemoryMechanism",
    "build_conversation_extraction_input",
    "conversation_memory_mechanism",
    "round_execution_context",
]
