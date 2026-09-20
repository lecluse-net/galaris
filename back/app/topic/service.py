"""Persistence and public Memory projection for global thematic dossiers."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Collection
from difflib import SequenceMatcher
from typing import Any, cast as type_cast
from uuid import UUID, uuid4

from sqlalchemy import Date, cast, func, or_, select, union_all, update
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.memory import (
    MemoryItem,
    MemoryConflictError,
    MemoryNotFoundError,
    SourceMemoryDocument,
    list_topic_linked_memories,
    list_topics_linked_documents,
    move_topic_memory_links,
    move_topic_contact_memory_scopes,
    purge_source_managed_item,
    rank_topic_projections,
    upsert_source_managed_item,
)
from core.database import get_db
from core.i18n import current_language, normalize_language, t
from core.util import local_timezone_name, month_bounds

from .models import Topic
from .schemas import (
    TopicCandidate,
    TopicClassification,
    TopicContentRead,
    TopicContentSummary,
    TopicCreate,
    TopicLinkedMemoryRead,
    TopicItemKind,
    TopicItemMutationResult,
    TopicItemPage,
    TopicItemRead,
    TopicItemSelector,
    TopicMutationResult,
    TopicMonthlyUsage,
    TopicPage,
    TopicRead,
    TopicRef,
    TopicRelatedAgent,
    TopicRelatedDocument,
    TopicRelatedTeam,
    TopicRelatedUser,
    TopicRoomRead,
    TopicRoundRead,
    TopicSplitRequest,
    TopicSelectionSplitRequest,
    TopicUpdate,
    TopicTaskRead,
    TopicVoiceTurnRead,
)


class TopicNotFoundError(LookupError):
    """The requested active Topic does not exist."""


class TopicConflictError(RuntimeError):
    """The requested Topic mutation conflicts with current state."""


_TITLE_SIMILARITY_REUSE = 0.9
_TITLE_TOKEN_REUSE = 0.8
_KEYWORD_REUSE = 0.75


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    characters: list[str] = []
    latin_base = False
    for character in decomposed:
        is_mark = unicodedata.category(character).startswith("M")
        if is_mark and (latin_base or not characters or characters[-1] == " "):
            continue
        if not is_mark:
            latin_base = unicodedata.name(character, "").startswith("LATIN ")
        characters.append(character if character.isalnum() or is_mark else " ")
    return " ".join(unicodedata.normalize("NFC", "".join(characters)).split())


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalized_text(value).split()
        if len(token) >= 3
    }


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _candidate_reuse_score(
    decision: TopicClassification, candidate: TopicCandidate
) -> float:
    proposed_title = _normalized_text(decision.title)
    candidate_title = _normalized_text(candidate.title)
    if proposed_title and proposed_title == candidate_title:
        return 1.0
    title_similarity = (
        SequenceMatcher(None, proposed_title, candidate_title).ratio()
        if proposed_title and candidate_title else 0.0
    )
    title_overlap = _overlap(_tokens(decision.title), _tokens(candidate.title))
    proposed_keywords = _tokens(" ".join(decision.keywords))
    candidate_keywords = _tokens(" ".join(candidate.keywords))
    keyword_overlap = _overlap(proposed_keywords, candidate_keywords)
    if title_similarity >= _TITLE_SIMILARITY_REUSE:
        return title_similarity
    if title_overlap >= _TITLE_TOKEN_REUSE and len(
        _tokens(decision.title) & _tokens(candidate.title)
    ) >= 2:
        return title_overlap
    if keyword_overlap >= _KEYWORD_REUSE and len(
        proposed_keywords & candidate_keywords
    ) >= 2:
        return keyword_overlap
    return 0.0


def _read(topic: Topic) -> TopicRead:
    return TopicRead.model_validate(topic)


def _markdown(topic: Topic) -> str:
    keywords = ", ".join(topic.keywords)
    sections = [f"# {topic.title}"]
    if topic.description:
        sections.append(topic.description)
    if keywords:
        language = normalize_language(topic.metadata_.get("language"))
        sections.append(f"{t('topic.memory.keywords', language)}: {keywords}")
    return "\n\n".join(sections)


def _topic_language(topic: Topic) -> str:
    return normalize_language(topic.metadata_.get("language"))


async def project_memory(topic: Topic) -> Topic:
    """Synchronize the deliberately public, ownerless Topic memory entry."""

    item = await upsert_source_managed_item(
        SourceMemoryDocument(
            source_kind="topic",
            source_ref=f"topic:{topic.id}",
            owner_agent_id=None,
            memory_item_id=topic.memory_item_id,
            title=topic.title,
            memory_type="semantic",
            content=_markdown(topic),
            filename=f"topic-{topic.id}.md",
            keywords=tuple(topic.keywords),
            metadata={
                "memory_role": "topic",
                "topic_id": str(topic.id),
                "language": _topic_language(topic),
            },
            visibility="public",
            topic_id=topic.id,
        )
    )
    if topic.memory_item_id != item.id:
        topic.memory_item_id = item.id
        await get_db().commit()
    return topic


async def _record(topic_id: UUID, *, for_update: bool = False) -> Topic | None:
    query = Topic.histo_filter(select(Topic).where(Topic.id == topic_id))
    if for_update:
        query = query.with_for_update()
    return await get_db().scalar(query)


async def _create_record(
    data: TopicCreate,
    *,
    created_by: str,
    language: str | None = None,
) -> Topic:
    resolved_language = normalize_language(language or await current_language())
    topic = Topic(
        title=data.title,
        description=data.description,
        keywords=data.keywords,
        metadata_={"created_by": created_by, "language": resolved_language},
    )
    get_db().add(topic)
    await get_db().flush()
    await project_memory(topic)
    await get_db().refresh(topic)
    return topic


async def create(data: TopicCreate) -> TopicRead:
    return _read(await _create_record(data, created_by="manual"))


async def update_topic(topic_id: UUID, data: TopicUpdate) -> TopicRead:
    topic = await _record(topic_id, for_update=True)
    if topic is None:
        raise TopicNotFoundError("Topic not found.")
    if topic.revision != data.revision:
        raise TopicConflictError("The Topic was modified by another operation.")
    topic.title = data.title
    topic.description = data.description
    topic.keywords = data.keywords
    await project_memory(topic)
    await get_db().refresh(topic)
    return _read(topic)


async def list_linked_memories(topic_id: UUID) -> list[TopicLinkedMemoryRead]:
    return await list_linked_memories_in_scope(topic_id)


async def list_linked_memories_in_scope(
    topic_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> list[TopicLinkedMemoryRead]:
    topic = await _record(topic_id)
    if topic is None:
        raise TopicNotFoundError("Topic not found.")
    if topic.memory_item_id is None:
        await project_memory(topic)
    assert topic.memory_item_id is not None
    try:
        linked = await list_topic_linked_memories(
            topic.memory_item_id,
            agent_ids=agent_ids,
        )
    except MemoryNotFoundError as exc:
        raise TopicNotFoundError("Topic projection not found.") from exc
    return [
        TopicLinkedMemoryRead(
            id=item.id,
            title=item.title,
            excerpt=item.excerpt,
            memory_type=item.memory_type,
            owner_agent_id=item.owner_agent_id,
            visibility=item.visibility,
        )
        for item in linked
    ]


async def merge(source_topic_id: UUID, target_topic_id: UUID) -> TopicMutationResult:
    if source_topic_id == target_topic_id:
        raise TopicConflictError("A Topic cannot be merged into itself.")
    source = await _record(source_topic_id, for_update=True)
    target = await _record(target_topic_id, for_update=True)
    if source is None or target is None:
        raise TopicNotFoundError("Source or target Topic not found.")
    if source.memory_item_id is None:
        await project_memory(source)
    if target.memory_item_id is None:
        await project_memory(target)
    assert source.memory_item_id is not None
    assert target.memory_item_id is not None
    try:
        moved = await move_topic_memory_links(
            source_topic_item_id=source.memory_item_id,
            target_topic_item_id=target.memory_item_id,
        )
        await move_topic_contact_memory_scopes(
            source_topic_item_id=source.memory_item_id,
            target_topic_item_id=target.memory_item_id,
        )
    except MemoryNotFoundError as exc:
        raise TopicNotFoundError("Source or target Topic projection not found.") from exc
    except MemoryConflictError as exc:
        raise TopicConflictError(str(exc)) from exc

    from app.conversation import ConversationRound
    from app.messenger import Message, Room
    from app.task import Task

    task_ids = list(
        (
            await get_db().scalars(
                update(Task)
                .where(Task.topic_id == source.id)
                .values(topic_id=target.id)
                .returning(Task.id)
            )
        ).all()
    )
    message_ids = list(
        (
            await get_db().scalars(
                update(Message)
                .where(Message.topic_id == source.id)
                .values(topic_id=target.id)
                .returning(Message.id)
            )
        ).all()
    )
    await get_db().execute(
        update(Room).where(Room.topic_id == source.id).values(topic_id=target.id)
    )
    round_ids = list(
        (
            await get_db().scalars(
                update(ConversationRound)
                .where(ConversationRound.topic_id == source.id)
                .values(topic_id=target.id)
                .returning(ConversationRound.id)
            )
        ).all()
    )
    await purge_source_managed_item(
        source_kind="topic",
        source_ref=f"topic:{source.id}",
        item_id=source.memory_item_id,
    )
    source.memory_item_id = None
    source.soft_delete()
    merged_ids = list(target.metadata_.get("merged_topic_ids", []))
    merged_ids.append(str(source.id))
    target.metadata_ = {
        **target.metadata_,
        "merged_topic_ids": list(dict.fromkeys(merged_ids)),
    }
    await get_db().commit()
    await get_db().refresh(target)
    return TopicMutationResult(
        topic=_read(target),
        moved_memory_links=moved,
        reassigned_tasks=len(task_ids),
        reassigned_voice_sessions=0,
        reassigned_voice_turns=0,
        reassigned_messages=len(message_ids),
        reassigned_conversation_rounds=len(round_ids),
    )


async def split(topic_id: UUID, data: TopicSplitRequest) -> TopicMutationResult:
    source = await _record(topic_id, for_update=True)
    if source is None:
        raise TopicNotFoundError("Topic not found.")
    if source.memory_item_id is None:
        await project_memory(source)
    assert source.memory_item_id is not None
    attached_ids = {
        item.id for item in await list_topic_linked_memories(source.memory_item_id)
    }
    if not set(data.memory_item_ids).issubset(attached_ids):
        raise TopicConflictError(
            "Some selected memories are no longer attached to the source Topic."
        )
    target = await _create_record(
        TopicCreate(
            title=data.title,
            description=data.description,
            keywords=data.keywords,
        ),
        created_by="manual_split",
    )
    assert target.memory_item_id is not None
    try:
        moved = await move_topic_memory_links(
            source_topic_item_id=source.memory_item_id,
            target_topic_item_id=target.memory_item_id,
            memory_item_ids=set(data.memory_item_ids),
        )
        await move_topic_contact_memory_scopes(
            source_topic_item_id=source.memory_item_id,
            target_topic_item_id=target.memory_item_id,
            memory_item_ids=set(data.memory_item_ids),
        )
    except MemoryNotFoundError as exc:
        raise TopicNotFoundError("Source or target Topic projection not found.") from exc
    except MemoryConflictError as exc:
        raise TopicConflictError(str(exc)) from exc
    split_ids = list(source.metadata_.get("split_topic_ids", []))
    split_ids.append(str(target.id))
    source.metadata_ = {
        **source.metadata_,
        "split_topic_ids": list(dict.fromkeys(split_ids)),
    }
    await get_db().commit()
    await get_db().refresh(target)
    return TopicMutationResult(topic=_read(target), moved_memory_links=moved)


async def delete_topic(topic_id: UUID) -> bool:
    topic = await _record(topic_id, for_update=True)
    if topic is None:
        return False

    from app.conversation import ConversationRound
    from app.messenger import Message, Room
    from app.task import Task

    await get_db().execute(
        update(Task).where(Task.topic_id == topic.id).values(topic_id=None)
    )
    await get_db().execute(
        update(Message)
        .where(Message.topic_id == topic.id)
        .values(topic_id=None, topic_overridden=False)
    )
    await get_db().execute(
        update(Room).where(Room.topic_id == topic.id).values(topic_id=None)
    )
    await get_db().execute(
        update(ConversationRound)
        .where(ConversationRound.topic_id == topic.id)
        .values(topic_id=None)
    )
    await purge_source_managed_item(
        source_kind="topic",
        source_ref=f"topic:{topic.id}",
        item_id=topic.memory_item_id,
    )
    topic.memory_item_id = None
    topic.soft_delete()
    await get_db().commit()
    return True


async def create_from_classification(
    decision: TopicClassification,
    *,
    language: str | None = None,
) -> Topic:
    if decision.action != "create":
        raise ValueError("Only create decisions can create a Topic.")
    topic_id = decision.topic_id or uuid4()
    normalized_title = _normalized_text(decision.title)
    if normalized_title:
        await get_db().execute(
            select(func.pg_advisory_xact_lock(func.hashtext(normalized_title)))
        )
        active_topics = list(
            (
                await get_db().execute(
                    Topic.histo_filter(select(Topic)).order_by(Topic.created_at)
                )
            ).scalars()
        )
        duplicate = next(
            (
                topic
                for topic in active_topics
                if _normalized_text(topic.title) == normalized_title
            ),
            None,
        )
        if duplicate is not None:
            return await project_memory(duplicate)
    existing = await get_db().scalar(
        Topic.histo_filter(select(Topic).where(Topic.id == topic_id))
    )
    if existing is not None:
        return await project_memory(existing)
    topic = Topic(
        id=topic_id,
        title=decision.title[:500],
        description=decision.description[:4_000],
        keywords=decision.keywords,
        metadata_={
            "created_by": "dream",
            "classification_confidence": decision.confidence,
            "language": normalize_language(language),
        },
    )
    get_db().add(topic)
    await get_db().flush()
    return await project_memory(topic)


async def resolve_classification(
    decision: TopicClassification,
    *,
    allowed_topic_ids: set[UUID],
    language: str | None = None,
) -> Topic:
    if decision.action == "create":
        return await create_from_classification(decision, language=language)
    assert decision.topic_id is not None
    if decision.topic_id not in allowed_topic_ids:
        raise ValueError("The selected Topic was not among the proposed candidates.")
    topic = await get_db().scalar(
        Topic.histo_filter(select(Topic).where(Topic.id == decision.topic_id))
    )
    if topic is None:
        raise LookupError("The selected Topic no longer exists.")
    if topic.memory_item_id is None:
        await project_memory(topic)
    return topic


async def list_candidates(
    *, activity: str = "", limit: int = 100
) -> list[TopicCandidate]:
    """Fuse lexical, vector and popular ranks into a bounded Topic shortlist."""

    from app.messenger import Message, Room
    from app.task import Task
    from app.conversation import ConversationRound

    activity_rows = union_all(
        select(Task.topic_id.label("topic_id")).where(Task.topic_id.is_not(None)),
        select(Message.topic_id.label("topic_id")).where(
            Message.topic_id.is_not(None)
        ),
        select(Room.topic_id.label("topic_id")).where(Room.topic_id.is_not(None)),
        select(ConversationRound.topic_id.label("topic_id")).where(
            ConversationRound.topic_id.is_not(None)
        ),
    ).subquery()
    usage = (
        select(
            activity_rows.c.topic_id,
            func.count().label("activity_count"),
        )
        .group_by(activity_rows.c.topic_id)
        .subquery()
    )
    rows = list(
        (
            await get_db().execute(
                Topic.histo_filter(
                    select(
                        Topic,
                        func.coalesce(usage.c.activity_count, 0).label(
                            "activity_count"
                        ),
                    ).outerjoin(usage, usage.c.topic_id == Topic.id)
                )
            )
        ).all()
    )
    candidates = [
        TopicCandidate(
            id=topic.id,
            title=topic.title,
            description=topic.description,
            keywords=topic.keywords,
            activity_count=int(activity_count),
        )
        for topic, activity_count in rows
    ]
    topic_id_by_memory_item_id = {
        topic.memory_item_id: topic.id
        for topic, _activity_count in rows
        if topic.memory_item_id is not None
    }
    activity_tokens = _tokens(activity)

    def lexical_score(candidate: TopicCandidate) -> float:
        candidate_tokens = _tokens(
            " ".join(
                [candidate.title, candidate.description, *candidate.keywords]
            )
        )
        return (
            len(activity_tokens & candidate_tokens)
            / math.sqrt(len(activity_tokens) * len(candidate_tokens))
            if activity_tokens and candidate_tokens
            else 0.0
        )

    lexical = sorted(
        candidates,
        key=lambda candidate: (
            lexical_score(candidate),
            math.log1p(candidate.activity_count),
            candidate.title.casefold(),
        ),
        reverse=True,
    )
    popular = sorted(
        candidates,
        key=lambda candidate: (
            candidate.activity_count,
            candidate.title.casefold(),
        ),
        reverse=True,
    )
    vector_ranking = await rank_topic_projections(
        activity,
        limit=min(500, max(limit * 3, 100)),
    )
    vector_topic_ids = [
        topic_id
        for match in vector_ranking.matches
        if (topic_id := topic_id_by_memory_item_id.get(match.memory_item_id))
        is not None
    ]
    scores: dict[UUID, float] = {}
    for weight, ranked_ids in (
        (1.0, [candidate.id for candidate in lexical]),
        (1.15, vector_topic_ids),
        (0.2, [candidate.id for candidate in popular]),
    ):
        for rank, topic_id in enumerate(ranked_ids, start=1):
            scores[topic_id] = scores.get(topic_id, 0.0) + weight / (60 + rank)
    fused = sorted(
        candidates,
        key=lambda candidate: (
            scores.get(candidate.id, 0.0),
            lexical_score(candidate),
            candidate.activity_count,
            candidate.title.casefold(),
        ),
        reverse=True,
    )

    if len(candidates) <= limit:
        return fused

    anchor_count = min(20, max(1, limit // 5))
    selected: list[TopicCandidate] = []
    selected_ids: set[UUID] = set()
    for candidate in [
        *fused[: max(0, limit - anchor_count)],
        *popular[:anchor_count],
        *fused,
    ]:
        if candidate.id in selected_ids:
            continue
        selected.append(candidate)
        selected_ids.add(candidate.id)
        if len(selected) >= limit:
            break
    return selected


async def prefer_reuse(
    decision: TopicClassification,
) -> tuple[TopicClassification, UUID | None]:
    """Convert a near-duplicate creation proposal to deterministic reuse."""

    if decision.action != "create":
        return decision, decision.topic_id
    candidates = await list_candidates(limit=5_000)
    scored = [
        (_candidate_reuse_score(decision, candidate), candidate)
        for candidate in candidates
    ]
    if not scored:
        return decision, None
    score, candidate = max(scored, key=lambda item: item[0])
    if score <= 0.0:
        return decision, None
    return (
        TopicClassification(
            action="reuse",
            topic_id=candidate.id,
            confidence=max(decision.confidence, score),
            reason=(
                decision.reason
                or "An existing dossier has equivalent normalized thematic metadata."
            ),
        ),
        candidate.id,
    )


async def list_keywords() -> list[str]:
    result = await get_db().scalars(
        select(Topic.keywords).where(Topic.deleted_at.is_(None))
    )
    keywords = {
        keyword.strip()
        for topic_keywords in result
        for keyword in topic_keywords
        if keyword.strip()
    }
    return sorted(keywords, key=str.casefold)


async def list_refs(topic_ids: set[UUID]) -> list[TopicRef]:
    """Resolve a bounded set of active Topic identities for compact UI badges."""

    if not topic_ids:
        return []
    rows = await get_db().execute(
        Topic.histo_filter(select(Topic).where(Topic.id.in_(topic_ids))).order_by(
            Topic.title, Topic.id
        )
    )
    return [TopicRef(id=topic.id, title=topic.title) for topic in rows.scalars()]


async def get_content(
    topic_id: UUID,
    *,
    limit: int = 50,
    agent_ids: Collection[int] | None = None,
) -> TopicContentRead:
    """Return a cross-domain, read-only recap of one thematic dossier."""

    from app.agent import Agent
    from app.connection import Connection
    from app.conversation import ConversationRound, ConversationRoundMessage
    from app.messenger import Message, Room
    from app.task import Task

    topic = await _record(topic_id)
    if topic is None:
        raise TopicNotFoundError("Topic not found.")

    input_text = (
        select(Message.text)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.message_id == Message.id,
        )
        .where(
            ConversationRoundMessage.round_id == ConversationRound.id,
            ConversationRoundMessage.role == "input",
        )
        .order_by(ConversationRoundMessage.sequence)
        .limit(1)
        .scalar_subquery()
    )
    output_text = (
        select(Message.text)
        .join(
            ConversationRoundMessage,
            ConversationRoundMessage.message_id == Message.id,
        )
        .where(
            ConversationRoundMessage.round_id == ConversationRound.id,
            ConversationRoundMessage.role == "output",
        )
        .order_by(
            ConversationRoundMessage.response_sequence.desc(),
            ConversationRoundMessage.sequence.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )

    task_query = Task.histo_filter(
        select(
            Task,
            Agent.first_name,
            Agent.last_name,
            Agent.code,
        )
        .outerjoin(Agent, Agent.id == Task.agent_id)
        .where(Task.topic_id == topic_id)
    )
    if agent_ids is not None:
        task_query = task_query.where(Task.agent_id.in_(agent_ids))
    task_rows = (
        await get_db().execute(
            task_query.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit)
        )
    ).all()
    task_count_query = Task.histo_filter(
        select(func.count(Task.id)).where(Task.topic_id == topic_id)
    )
    if agent_ids is not None:
        task_count_query = task_count_query.where(Task.agent_id.in_(agent_ids))
    task_count = int(await get_db().scalar(task_count_query) or 0)

    round_room_ids = (
        select(ConversationRound.room_id.label("room_id"))
        .join(Room, Room.id == ConversationRound.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .where(ConversationRound.topic_id == topic_id)
    )
    message_room_ids = (
        select(Message.messenger_room_id.label("room_id"))
        .join(Connection, Connection.id == Message.connection_id)
        .where(
        Message.topic_id == topic_id,
        Message.messenger_room_id.is_not(None),
        )
    )
    default_room_ids = select(Room.id.label("room_id")).where(
        Room.topic_id == topic_id
    )
    task_room_ids = (
        select(Room.id.label("room_id"))
        .join(
            Task,
            (Task.messenger_connection_id == Room.connection_id)
            & (Task.message_group_id == Room.external_id),
        )
        .where(Task.topic_id == topic_id, Task.deleted_at.is_(None))
    )
    if agent_ids is not None:
        round_room_ids = round_room_ids.where(Connection.agent_id.in_(agent_ids))
        message_room_ids = message_room_ids.where(Connection.agent_id.in_(agent_ids))
        task_room_ids = task_room_ids.where(Task.agent_id.in_(agent_ids))
        default_room_ids = default_room_ids.join(
            Connection, Connection.id == Room.connection_id
        ).where(Connection.agent_id.in_(agent_ids))
    room_ids = union_all(
        round_room_ids,
        message_room_ids,
        task_room_ids,
        default_room_ids,
    ).subquery()
    room_query = Room.histo_filter(
        select(Room)
        .join(room_ids, room_ids.c.room_id == Room.id)
        .distinct()
    )
    room_rows = list(
        (
            await get_db().scalars(
                room_query.order_by(Room.label, Room.external_id).limit(limit)
            )
        ).all()
    )
    room_count = int(
        await get_db().scalar(
            select(func.count(func.distinct(room_ids.c.room_id))).select_from(room_ids)
        )
        or 0
    )

    round_columns = (
        ConversationRound,
        Room.label,
        input_text.label("input_text"),
        output_text.label("output_text"),
    )
    text_round_query = (
        select(*round_columns)
            .join(Room, Room.id == ConversationRound.room_id)
            .join(Connection, Connection.id == Room.connection_id)
            .where(
                ConversationRound.topic_id == topic_id,
                ConversationRound.voice_session_id.is_(None),
            )
            .order_by(ConversationRound.created_at.desc(), ConversationRound.id.desc())
            .limit(limit)
    )
    voice_turn_query = (
        select(*round_columns)
            .join(Room, Room.id == ConversationRound.room_id)
            .join(Connection, Connection.id == Room.connection_id)
            .where(
                ConversationRound.topic_id == topic_id,
                ConversationRound.voice_session_id.is_not(None),
            )
            .order_by(ConversationRound.created_at.desc(), ConversationRound.id.desc())
            .limit(limit)
    )
    round_count_query = (
        select(
                func.count(ConversationRound.id).filter(
                    ConversationRound.voice_session_id.is_(None)
                ),
                func.count(ConversationRound.id).filter(
                    ConversationRound.voice_session_id.is_not(None)
                ),
            )
            .join(Room, Room.id == ConversationRound.room_id)
            .join(Connection, Connection.id == Room.connection_id)
            .where(ConversationRound.topic_id == topic_id)
    )
    if agent_ids is not None:
        text_round_query = text_round_query.where(Connection.agent_id.in_(agent_ids))
        voice_turn_query = voice_turn_query.where(Connection.agent_id.in_(agent_ids))
        round_count_query = round_count_query.where(Connection.agent_id.in_(agent_ids))
    text_round_rows = (await get_db().execute(text_round_query)).all()
    voice_turn_rows = (await get_db().execute(voice_turn_query)).all()
    text_round_count, voice_turn_count = (
        await get_db().execute(round_count_query)
    ).one()

    memories = (
        await list_linked_memories_in_scope(topic_id, agent_ids=agent_ids)
        if topic.memory_item_id is not None
        else []
    )
    documents: list[TopicRelatedDocument] = []
    if topic.memory_item_id is not None:
        linked_documents = await list_topics_linked_documents(
            {topic.memory_item_id},
            agent_ids=agent_ids,
        )
        documents = [
            TopicRelatedDocument(
                id=document.id,
                title=document.title,
                filename=document.filename,
            )
            for document in linked_documents
        ]

    return TopicContentRead(
        topic=_read(topic),
        summary=TopicContentSummary(
            rooms=room_count,
            tasks=task_count,
            conversation_rounds=int(text_round_count),
            voice_turns=int(voice_turn_count),
            memories=len(memories),
            documents=len(documents),
        ),
        rooms=[
            TopicRoomRead(
                id=room.id,
                connection_id=room.connection_id,
                external_id=room.external_id,
                label=room.label,
                kind=room.kind,
                conversation_type=room.conversation_type,
            )
            for room in room_rows
        ],
        tasks=[
            TopicTaskRead(
                id=task.id,
                label=task.label,
                objective=task.objective,
                status=task.status.value,
                agent_id=task.agent_id,
                agent_name=(
                    f"{first_name or ''} {last_name or ''}".strip() or str(code or "") or None
                ),
                created_at=task.created_at,
            )
            for task, first_name, last_name, code in task_rows
        ],
        conversation_rounds=[
            TopicRoundRead(
                id=round_.id,
                room_id=round_.room_id,
                room_label=str(room_label),
                status=round_.status,
                preview=str(round_.effective_objective or request_text or ""),
                response=str(response_text or ""),
                created_at=round_.created_at,
            )
            for round_, room_label, request_text, response_text in text_round_rows
        ],
        voice_turns=[
            TopicVoiceTurnRead(
                id=round_.id,
                session_id=round_.voice_session_id,
                sequence=int(round_.sequence or 0),
                room_id=round_.room_id,
                room_label=str(room_label),
                status=round_.status,
                preview=str(round_.effective_objective or request_text or ""),
                response=str(response_text or ""),
                created_at=round_.created_at,
            )
            for round_, room_label, request_text, response_text in voice_turn_rows
            if round_.voice_session_id is not None
        ],
        memories=memories[:limit],
        documents=documents[:limit],
    )


def _bounded_preview(value: str | None, *, limit: int = 500) -> str:
    normalized = " ".join((value or "").split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1].rstrip() + "…"


async def list_items(
    topic_id: UUID,
    *,
    item_type: TopicItemKind | None = None,
    offset: int = 0,
    limit: int = 50,
) -> TopicItemPage:
    """List every canonical object directly or graph-linked to one Topic."""

    from app.conversation import ConversationRound
    from app.messenger import Message
    from app.task import Task

    if await _record(topic_id) is None:
        raise TopicNotFoundError("Topic not found.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to zero")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    requested: tuple[TopicItemKind, ...] = (
        (item_type,)
        if item_type is not None
        else (
            "task",
            "message",
            "conversation_round",
            "voice_turn",
            "memory",
            "document",
        )
    )
    fetch_limit = offset + limit
    items: list[TopicItemRead] = []
    total = 0

    if "task" in requested:
        task_query = Task.histo_filter(
            select(Task).where(Task.topic_id == topic_id)
        )
        total += int(
            await get_db().scalar(
                Task.histo_filter(
                    select(func.count(Task.id)).where(Task.topic_id == topic_id)
                )
            )
            or 0
        )
        tasks = list(
            (
                await get_db().scalars(
                    task_query.order_by(Task.created_at.desc(), Task.id.desc()).limit(fetch_limit)
                )
            ).all()
        )
        items.extend(
            TopicItemRead(
                item_type="task",
                item_id=task.id,
                topic_id=topic_id,
                title=task.label,
                preview=_bounded_preview(task.objective),
                created_at=task.created_at,
                metadata={
                    "status": task.status.value,
                    "agent_id": task.agent_id,
                    "revision": task.revision,
                },
            )
            for task in tasks
        )

    if "message" in requested:
        message_query = Message.histo_filter(
            select(Message).where(Message.topic_id == topic_id)
        )
        total += int(
            await get_db().scalar(
                Message.histo_filter(
                    select(func.count(Message.id)).where(Message.topic_id == topic_id)
                )
            )
            or 0
        )
        messages = list(
            (
                await get_db().scalars(
                    message_query.order_by(Message.created_at.desc(), Message.id.desc()).limit(fetch_limit)
                )
            ).all()
        )
        items.extend(
            TopicItemRead(
                item_type="message",
                item_id=message.id,
                topic_id=topic_id,
                title=_bounded_preview(message.text, limit=120)
                or f"{message.direction} message",
                preview=_bounded_preview(message.text),
                created_at=message.created_at,
                metadata={
                    "direction": message.direction,
                    "platform": message.platform,
                    "status": message.status,
                    "connection_id": message.connection_id,
                },
            )
            for message in messages
        )

    for raw_kind, voice in (("conversation_round", False), ("voice_turn", True)):
        kind = type_cast(TopicItemKind, raw_kind)
        if kind not in requested:
            continue
        voice_clause = (
            ConversationRound.voice_session_id.is_not(None)
            if voice
            else ConversationRound.voice_session_id.is_(None)
        )
        total += int(
            await get_db().scalar(
                select(func.count(ConversationRound.id)).where(
                    ConversationRound.topic_id == topic_id,
                    voice_clause,
                )
            )
            or 0
        )
        rounds = list(
            (
                await get_db().scalars(
                    select(ConversationRound)
                    .where(ConversationRound.topic_id == topic_id, voice_clause)
                    .order_by(ConversationRound.created_at.desc(), ConversationRound.id.desc())
                    .limit(fetch_limit)
                )
            ).all()
        )
        items.extend(
            TopicItemRead(
                item_type=kind,
                item_id=round_.id,
                topic_id=topic_id,
                title=(
                    f"Voice turn {round_.sequence or 0}"
                    if voice
                    else "Conversation round"
                ),
                preview=_bounded_preview(round_.effective_objective),
                created_at=round_.created_at,
                metadata={
                    "status": round_.status,
                    "room_id": str(round_.room_id),
                    "voice_session_id": (
                        str(round_.voice_session_id)
                        if round_.voice_session_id is not None
                        else None
                    ),
                },
            )
            for round_ in rounds
        )

    if "memory" in requested or "document" in requested:
        topic = await _record(topic_id)
        assert topic is not None
        if topic.memory_item_id is not None:
            linked = await list_topic_linked_memories(topic.memory_item_id)
            for kind in ("memory", "document"):
                if kind not in requested:
                    continue
                matches = [
                    item
                    for item in linked
                    if (item.node_kind == "document") == (kind == "document")
                ]
                matches.sort(
                    key=lambda item: (item.created_at.timestamp(), str(item.id)),
                    reverse=True,
                )
                total += len(matches)
                items.extend(
                    TopicItemRead(
                        item_type=kind,
                        item_id=item.id,
                        topic_id=topic_id,
                        title=item.title,
                        preview=_bounded_preview(item.excerpt),
                        created_at=item.created_at,
                        metadata={
                            "memory_type": item.memory_type,
                            "owner_agent_id": item.owner_agent_id,
                            "visibility": item.visibility,
                            "filename": item.filename,
                        },
                    )
                    for item in matches[:fetch_limit]
                )

    items.sort(
        key=lambda item: (
            item.created_at.timestamp() if item.created_at is not None else 0.0,
            str(item.item_id),
        ),
        reverse=True,
    )
    return TopicItemPage(
        items=items[offset : offset + limit],
        total=total,
        offset=offset,
        limit=limit,
    )


async def reassign_item(
    source_topic_id: UUID,
    target_topic_id: UUID,
    selector: TopicItemSelector,
) -> TopicItemMutationResult:
    """Move one exact Topic membership after checking its current source."""

    from app.conversation import ConversationRound
    from app.messenger import Message
    from app.task import Task, TaskUpdate, task_service

    if source_topic_id == target_topic_id:
        raise TopicConflictError("Source and target Topics must differ.")
    source = await _record(source_topic_id, for_update=True)
    target = await _record(target_topic_id, for_update=True)
    if source is None or target is None:
        raise TopicNotFoundError("Source or target Topic not found.")

    kind = selector.item_type
    if kind == "task":
        task = await get_db().scalar(
            Task.histo_filter(select(Task).where(Task.id == selector.item_id)).with_for_update()
        )
        if task is None or task.topic_id != source_topic_id:
            raise TopicConflictError("Task is not attached to the source Topic.")
        updated_task = await task_service.update(
            task.id,
            TaskUpdate(
                expected_revision=task.revision,
                topic_id=target_topic_id,
            ),
        )
        if updated_task is None:
            raise TopicConflictError("Task disappeared during Topic reassignment.")
    elif kind == "message":
        message = await get_db().scalar(
            Message.histo_filter(select(Message).where(Message.id == selector.item_id)).with_for_update()
        )
        if message is None or message.topic_id != source_topic_id:
            raise TopicConflictError("Message is not attached to the source Topic.")
        message.topic_id = target_topic_id
    elif kind in {"conversation_round", "voice_turn"}:
        round_ = await get_db().scalar(
            select(ConversationRound)
            .where(ConversationRound.id == selector.item_id)
            .with_for_update()
        )
        expected_voice = kind == "voice_turn"
        if (
            round_ is None
            or round_.topic_id != source_topic_id
            or (round_.voice_session_id is not None) != expected_voice
        ):
            raise TopicConflictError(f"{kind} is not attached to the source Topic.")
        round_.topic_id = target_topic_id
    else:
        if source.memory_item_id is None:
            raise TopicConflictError("The source Topic has no Memory projection.")
        if target.memory_item_id is None:
            await project_memory(target)
        assert target.memory_item_id is not None
        linked = await list_topic_linked_memories(source.memory_item_id)
        selected = next((item for item in linked if item.id == selector.item_id), None)
        expected_document = kind == "document"
        if selected is None or (selected.node_kind == "document") != expected_document:
            raise TopicConflictError(f"{kind} is not attached to the source Topic.")
        try:
            await move_topic_memory_links(
                source_topic_item_id=source.memory_item_id,
                target_topic_item_id=target.memory_item_id,
                memory_item_ids={selector.item_id},
            )
            await move_topic_contact_memory_scopes(
                source_topic_item_id=source.memory_item_id,
                target_topic_item_id=target.memory_item_id,
                memory_item_ids={selector.item_id},
            )
        except MemoryNotFoundError as exc:
            raise TopicNotFoundError("Source or target Topic projection not found.") from exc
        except MemoryConflictError as exc:
            raise TopicConflictError(str(exc)) from exc

    await get_db().commit()
    item = await _read_attached_item(target, selector)
    if item is None:
        raise TopicConflictError("The reassigned item could not be reloaded.")
    return TopicItemMutationResult(
        item=item,
        source_topic_id=source_topic_id,
        target_topic_id=target_topic_id,
    )


async def _item_is_attached(
    topic: Topic,
    selector: TopicItemSelector,
) -> bool:
    from app.conversation import ConversationRound
    from app.messenger import Message
    from app.task import Task

    kind = selector.item_type
    if kind == "task":
        return (
            await get_db().scalar(
                Task.histo_filter(
                    select(Task.id).where(
                        Task.id == selector.item_id,
                        Task.topic_id == topic.id,
                    )
                )
            )
            is not None
        )
    if kind == "message":
        return (
            await get_db().scalar(
                Message.histo_filter(
                    select(Message.id).where(
                        Message.id == selector.item_id,
                        Message.topic_id == topic.id,
                    )
                )
            )
            is not None
        )
    if kind in {"conversation_round", "voice_turn"}:
        round_ = await get_db().scalar(
            select(ConversationRound).where(
                ConversationRound.id == selector.item_id,
                ConversationRound.topic_id == topic.id,
            )
        )
        return round_ is not None and (
            (round_.voice_session_id is not None) == (kind == "voice_turn")
        )
    if topic.memory_item_id is None:
        return False
    linked = await list_topic_linked_memories(topic.memory_item_id)
    selected = next((item for item in linked if item.id == selector.item_id), None)
    return selected is not None and (
        (selected.node_kind == "document") == (kind == "document")
    )


async def _read_attached_item(
    topic: Topic,
    selector: TopicItemSelector,
) -> TopicItemRead | None:
    from app.conversation import ConversationRound
    from app.messenger import Message
    from app.task import Task

    kind = selector.item_type
    if kind == "task":
        task = await get_db().scalar(
            Task.histo_filter(
                select(Task).where(
                    Task.id == selector.item_id,
                    Task.topic_id == topic.id,
                )
            )
        )
        if task is None:
            return None
        return TopicItemRead(
            item_type="task",
            item_id=task.id,
            topic_id=topic.id,
            title=task.label,
            preview=_bounded_preview(task.objective),
            created_at=task.created_at,
            metadata={
                "status": task.status.value,
                "agent_id": task.agent_id,
                "revision": task.revision,
            },
        )
    if kind == "message":
        message = await get_db().scalar(
            Message.histo_filter(
                select(Message).where(
                    Message.id == selector.item_id,
                    Message.topic_id == topic.id,
                )
            )
        )
        if message is None:
            return None
        return TopicItemRead(
            item_type="message",
            item_id=message.id,
            topic_id=topic.id,
            title=_bounded_preview(message.text, limit=120)
            or f"{message.direction} message",
            preview=_bounded_preview(message.text),
            created_at=message.created_at,
            metadata={
                "direction": message.direction,
                "platform": message.platform,
                "status": message.status,
                "connection_id": message.connection_id,
            },
        )
    if kind in {"conversation_round", "voice_turn"}:
        round_ = await get_db().scalar(
            select(ConversationRound).where(
                ConversationRound.id == selector.item_id,
                ConversationRound.topic_id == topic.id,
            )
        )
        if round_ is None or (
            (round_.voice_session_id is not None) != (kind == "voice_turn")
        ):
            return None
        return TopicItemRead(
            item_type=kind,
            item_id=round_.id,
            topic_id=topic.id,
            title=(
                f"Voice turn {round_.sequence or 0}"
                if kind == "voice_turn"
                else "Conversation round"
            ),
            preview=_bounded_preview(round_.effective_objective),
            created_at=round_.created_at,
            metadata={
                "status": round_.status,
                "room_id": str(round_.room_id),
                "voice_session_id": (
                    str(round_.voice_session_id)
                    if round_.voice_session_id is not None
                    else None
                ),
            },
        )
    if topic.memory_item_id is None:
        return None
    linked = await list_topic_linked_memories(topic.memory_item_id)
    memory = next((item for item in linked if item.id == selector.item_id), None)
    if memory is None or (
        (memory.node_kind == "document") != (kind == "document")
    ):
        return None
    return TopicItemRead(
        item_type=kind,
        item_id=memory.id,
        topic_id=topic.id,
        title=memory.title,
        preview=_bounded_preview(memory.excerpt),
        created_at=memory.created_at,
        metadata={
            "memory_type": memory.memory_type,
            "owner_agent_id": memory.owner_agent_id,
            "visibility": memory.visibility,
            "filename": memory.filename,
        },
    )


async def split_selection(
    topic_id: UUID,
    data: TopicSelectionSplitRequest,
) -> TopicMutationResult:
    """Create a Topic and move an explicit heterogeneous selection into it."""

    source = await _record(topic_id, for_update=True)
    if source is None:
        raise TopicNotFoundError("Topic not found.")
    memory_selectors = [
        selector
        for selector in data.items
        if selector.item_type in {"memory", "document"}
    ]
    direct_selectors = [
        selector
        for selector in data.items
        if selector.item_type not in {"memory", "document"}
    ]
    for selector in direct_selectors:
        if not await _item_is_attached(source, selector):
            raise TopicConflictError(
                "Some selected items are no longer attached to the source Topic."
            )
    if memory_selectors:
        if source.memory_item_id is None:
            raise TopicConflictError("The source Topic has no Memory projection.")
        linked_by_id = {
            item.id: item
            for item in await list_topic_linked_memories(source.memory_item_id)
        }
        if any(
            (item := linked_by_id.get(selector.item_id)) is None
            or (item.node_kind == "document")
            != (selector.item_type == "document")
            for selector in memory_selectors
        ):
            raise TopicConflictError(
                "Some selected items are no longer attached to the source Topic."
            )

    target = await _create_record(
        TopicCreate(
            title=data.title,
            description=data.description,
            keywords=data.keywords,
        ),
        created_by="tool_split",
    )
    counts: dict[TopicItemKind, int] = {
        "task": 0,
        "message": 0,
        "conversation_round": 0,
        "voice_turn": 0,
        "memory": 0,
        "document": 0,
    }
    if memory_selectors:
        assert source.memory_item_id is not None
        assert target.memory_item_id is not None
        memory_ids = {selector.item_id for selector in memory_selectors}
        try:
            await move_topic_memory_links(
                source_topic_item_id=source.memory_item_id,
                target_topic_item_id=target.memory_item_id,
                memory_item_ids=memory_ids,
            )
            await move_topic_contact_memory_scopes(
                source_topic_item_id=source.memory_item_id,
                target_topic_item_id=target.memory_item_id,
                memory_item_ids=memory_ids,
            )
        except MemoryNotFoundError as exc:
            raise TopicNotFoundError(
                "Source or target Topic projection not found."
            ) from exc
        except MemoryConflictError as exc:
            raise TopicConflictError(str(exc)) from exc
        for selector in memory_selectors:
            counts[selector.item_type] += 1
    for selector in direct_selectors:
        await reassign_item(topic_id, target.id, selector)
        counts[selector.item_type] += 1

    split_ids = list(source.metadata_.get("split_topic_ids", []))
    split_ids.append(str(target.id))
    source.metadata_ = {
        **source.metadata_,
        "split_topic_ids": list(dict.fromkeys(split_ids)),
    }
    await get_db().commit()
    await get_db().refresh(target)
    return TopicMutationResult(
        topic=_read(target),
        moved_memory_links=counts["memory"] + counts["document"],
        reassigned_tasks=counts["task"],
        reassigned_messages=counts["message"],
        reassigned_conversation_rounds=counts["conversation_round"],
        reassigned_voice_turns=counts["voice_turn"],
    )


def _llm_call_topic_id() -> ColumnElement[UUID | None]:
    from app.conversation import ConversationProcessLink, ConversationRound
    from app.llm import LLMCall
    from app.process import ProcessRun
    from app.task import Task

    process_task = aliased(Task)
    process_topic_id = (
        select(process_task.topic_id)
        .join(ProcessRun, ProcessRun.task_id == process_task.id)
        .where(ProcessRun.id == LLMCall.process_run_id)
        .scalar_subquery()
    )
    process_round = aliased(ConversationRound)
    process_conversation_topic_id = (
        select(process_round.topic_id)
        .join(
            ConversationProcessLink,
            ConversationProcessLink.round_id == process_round.id,
        )
        .where(ConversationProcessLink.process_run_id == LLMCall.process_run_id)
        .scalar_subquery()
    )
    return type_cast(
        ColumnElement[UUID | None],
        func.coalesce(
            Task.topic_id,
            process_topic_id,
            process_conversation_topic_id,
            ConversationRound.topic_id,
        ),
    )


def _join_llm_call_topics(query: Select[Any]) -> Select[Any]:
    from app.conversation import ConversationRound
    from app.llm import LLMCall
    from app.task import Task

    return (
        query
        .outerjoin(Task, Task.id == LLMCall.task_id)
        .outerjoin(
            ConversationRound,
            ConversationRound.id == LLMCall.conversation_round_id,
        )
    )


def _llm_call_agent_id() -> ColumnElement[int | None]:
    from app.connection import Connection
    from app.conversation import ConversationRound
    from app.llm import LLMCall
    from app.messenger import Room
    from app.process import ProcessRun
    from app.task import Task

    conversation_agent_id = (
        select(Connection.agent_id)
        .join(Room, Room.connection_id == Connection.id)
        .where(Room.id == ConversationRound.room_id)
        .scalar_subquery()
    )
    process_agent_id = (
        select(ProcessRun.launcher_agent_id)
        .where(ProcessRun.id == LLMCall.process_run_id)
        .scalar_subquery()
    )
    return type_cast(
        ColumnElement[int | None],
        func.coalesce(
            LLMCall.agent_id,
            Task.agent_id,
            conversation_agent_id,
            process_agent_id,
        ),
    )


async def _available_usage_months(
    selected_month: str,
    *,
    timezone_name: str,
    agent_ids: Collection[int] | None = None,
) -> list[str]:
    from app.llm import LLMCall

    topic_id = _llm_call_topic_id()
    call_month = cast(
        func.date_trunc("month", func.timezone(timezone_name, LLMCall.started_at)),
        Date,
    ).label("month")
    query = _join_llm_call_topics(
        select(call_month).select_from(LLMCall)
    )
    query = (
        query
        .where(topic_id.is_not(None))
        .distinct()
        .order_by(call_month.desc())
    )
    if agent_ids is not None:
        query = query.where(_llm_call_agent_id().in_(agent_ids))
    result = await get_db().execute(query)
    months = {
        f"{value.year:04d}-{value.month:02d}"
        for value in result.scalars().all()
    }
    months.add(selected_month)
    current_month, _, _ = month_bounds(None, timezone_name=timezone_name)
    months.add(current_month)
    return sorted(months, reverse=True)


async def _related_agents(
    topic_ids: set[UUID],
    *,
    agent_ids: Collection[int] | None = None,
) -> dict[UUID, list[TopicRelatedAgent]]:
    from app.agent import Agent
    from app.connection import Connection
    from app.conversation import ConversationRound
    from app.messenger import Message
    from app.task import Task
    from app.messenger import Room

    references = union_all(
        select(Task.topic_id.label("topic_id"), Task.agent_id.label("agent_id")).where(
            Task.topic_id.in_(topic_ids), Task.agent_id.is_not(None)
        ),
        select(
            Task.topic_id.label("topic_id"),
            Task.requester_agent_id.label("agent_id"),
        ).where(Task.topic_id.in_(topic_ids), Task.requester_agent_id.is_not(None)),
        select(
            ConversationRound.topic_id.label("topic_id"),
            Connection.agent_id.label("agent_id"),
        )
        .join(Room, Room.id == ConversationRound.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .where(ConversationRound.topic_id.in_(topic_ids)),
        select(
            Message.topic_id.label("topic_id"),
            Connection.agent_id.label("agent_id"),
        )
        .join(Connection, Connection.id == Message.connection_id)
        .where(Message.topic_id.in_(topic_ids)),
    ).subquery()
    query = (
        select(
            references.c.topic_id,
            Agent.id,
            Agent.first_name,
            Agent.last_name,
            Agent.code,
        )
        .join(Agent, Agent.id == references.c.agent_id)
        .distinct()
        .order_by(Agent.first_name, Agent.last_name, Agent.id)
    )
    if agent_ids is not None:
        query = query.where(Agent.id.in_(agent_ids))
    rows = await get_db().execute(query)
    related: dict[UUID, list[TopicRelatedAgent]] = {}
    for topic_id, agent_id, first_name, last_name, code in rows:
        name = f"{first_name} {last_name}".strip() or str(code)
        related.setdefault(topic_id, []).append(
            TopicRelatedAgent(id=agent_id, name=name)
        )
    return related


async def _related_teams(
    agents_by_topic: dict[UUID, list[TopicRelatedAgent]],
) -> dict[UUID, list[TopicRelatedTeam]]:
    """Current teams of the visible participants, including legacy memberships."""
    from app.agent import Agent, AgentGroup, AgentTeamModel

    agent_ids = {agent.id for agents in agents_by_topic.values() for agent in agents}
    if not agent_ids:
        return {}
    memberships = union_all(
        select(Agent.id.label("agent_id"), Agent.group_id.label("team_id")).where(
            Agent.id.in_(agent_ids), Agent.group_id.is_not(None)
        ),
        select(AgentTeamModel.agent_id, AgentTeamModel.team_id).where(
            AgentTeamModel.agent_id.in_(agent_ids)
        ),
    ).subquery()
    rows = await get_db().execute(
        select(memberships.c.agent_id, AgentGroup.id, AgentGroup.name)
        .join(AgentGroup, AgentGroup.id == memberships.c.team_id)
        .where(AgentGroup.deleted_at.is_(None))
        .order_by(AgentGroup.order, AgentGroup.name, AgentGroup.id)
    )
    topics_by_agent: dict[int, set[UUID]] = {}
    for topic_id, agents in agents_by_topic.items():
        for agent in agents:
            topics_by_agent.setdefault(agent.id, set()).add(topic_id)
    teams_by_topic: dict[UUID, dict[int, TopicRelatedTeam]] = {}
    for agent_id, team_id, name in rows:
        for topic_id in topics_by_agent[agent_id]:
            teams_by_topic.setdefault(topic_id, {})[team_id] = TopicRelatedTeam(
                id=team_id, name=name
            )
    return {topic_id: list(teams.values()) for topic_id, teams in teams_by_topic.items()}


async def _related_users(
    topic_ids: set[UUID],
    *,
    agent_ids: Collection[int] | None = None,
) -> dict[UUID, list[TopicRelatedUser]]:
    from app.connection import Connection
    from app.conversation import ConversationRound
    from app.messenger import Message, Room
    from app.task import Task

    task_references = select(
            Task.topic_id.label("topic_id"),
            Task.contact_memory_item_id.label("contact_item_id"),
        ).where(
            Task.topic_id.in_(topic_ids),
            Task.contact_memory_item_id.is_not(None),
        )
    round_references = (
        select(
            ConversationRound.topic_id.label("topic_id"),
            ConversationRound.contact_memory_item_id.label("contact_item_id"),
        )
        .join(Room, Room.id == ConversationRound.room_id)
        .join(Connection, Connection.id == Room.connection_id)
        .where(
            ConversationRound.topic_id.in_(topic_ids),
            ConversationRound.contact_memory_item_id.is_not(None),
        )
    )
    message_references = (
        select(
            Message.topic_id.label("topic_id"),
            Message.contact_memory_item_id.label("contact_item_id"),
        )
        .join(Connection, Connection.id == Message.connection_id)
        .where(
            Message.topic_id.in_(topic_ids),
            Message.contact_memory_item_id.is_not(None),
        )
    )
    if agent_ids is not None:
        task_references = task_references.where(Task.agent_id.in_(agent_ids))
        round_references = round_references.where(Connection.agent_id.in_(agent_ids))
        message_references = message_references.where(Connection.agent_id.in_(agent_ids))
    references = union_all(
        task_references,
        round_references,
        message_references,
    ).subquery()
    rows = await get_db().execute(
        select(references.c.topic_id, MemoryItem)
        .join(MemoryItem, MemoryItem.id == references.c.contact_item_id)
        .where(
            MemoryItem.deleted_at.is_(None),
            MemoryItem.managed_source_kind == "messenger_contact",
        )
        .distinct()
        .order_by(references.c.topic_id, MemoryItem.title, MemoryItem.id)
    )
    related: dict[UUID, list[TopicRelatedUser]] = {}
    seen: set[tuple[UUID, UUID]] = set()
    for topic_id, item in rows:
        key = (topic_id, item.id)
        if key in seen:
            continue
        seen.add(key)
        display_name = str(item.metadata_.get("display_name") or "").strip()
        user_id = str(item.metadata_.get("user_id") or "").strip()
        related.setdefault(topic_id, []).append(
            TopicRelatedUser(
                id=item.id,
                display_name=display_name or user_id or item.title,
                user_id=user_id,
            )
        )
    return related


async def list_page(
    *,
    skip: int,
    limit: int,
    search: str | None,
    month: str | None = None,
    agent_ids: Collection[int] | None = None,
) -> TopicPage:
    from app.llm import LLMCall

    timezone_name = local_timezone_name()
    normalized_month, start, end = month_bounds(
        month,
        timezone_name=timezone_name,
    )
    topic_id = _llm_call_topic_id()
    usage_query = select(
            topic_id.label("topic_id"),
            func.count(LLMCall.id).label("llm_calls"),
            func.coalesce(func.sum(LLMCall.inference_cost), 0.0).label("inference_cost"),
        ).select_from(LLMCall)
    usage_query = _join_llm_call_topics(usage_query)
    usage = (
        usage_query
        .where(
            topic_id.is_not(None),
            LLMCall.started_at >= start,
            LLMCall.started_at < end,
        )
        .group_by(topic_id)
    )
    if agent_ids is not None:
        usage = usage.where(_llm_call_agent_id().in_(agent_ids))
    usage = usage.subquery()
    query = Topic.histo_filter(select(Topic))
    normalized = (search or "").strip()
    if normalized:
        pattern = f"%{normalized}%"
        query = query.where(
            or_(
                Topic.title.ilike(pattern),
                Topic.description.ilike(pattern),
            )
        )
    count_query = select(func.count()).select_from(query.subquery())
    total = int(await get_db().scalar(count_query) or 0)
    rows = await get_db().execute(
        query.add_columns(
            func.coalesce(usage.c.inference_cost, 0.0).label("inference_cost"),
            func.coalesce(usage.c.llm_calls, 0).label("llm_calls"),
        )
        .outerjoin(usage, usage.c.topic_id == Topic.id)
        .order_by(Topic.updated_at.desc().nullslast(), Topic.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    topic_rows = list(rows)
    page_topics = [topic for topic, _inference_cost, _llm_calls in topic_rows]
    topic_ids = {topic.id for topic in page_topics}
    agents_by_topic = (
        await _related_agents(topic_ids, agent_ids=agent_ids)
        if topic_ids
        else {}
    )
    users_by_topic = (
        await _related_users(topic_ids, agent_ids=agent_ids)
        if topic_ids
        else {}
    )
    teams_by_topic = await _related_teams(agents_by_topic)
    documents_by_topic: dict[UUID, list[TopicRelatedDocument]] = {}
    topic_id_by_projection_id = {
        topic.memory_item_id: topic.id
        for topic in page_topics
        if topic.memory_item_id is not None
    }
    documents = await list_topics_linked_documents(
        set(topic_id_by_projection_id),
        agent_ids=agent_ids,
    )
    for document in documents:
        topic_id_for_document = topic_id_by_projection_id.get(document.topic_item_id)
        if topic_id_for_document is None:
            continue
        documents_by_topic.setdefault(topic_id_for_document, []).append(
            TopicRelatedDocument(
                id=document.id,
                title=document.title,
                filename=document.filename,
            )
        )
    items = [
        TopicMonthlyUsage(
            **_read(topic).model_dump(),
            inference_cost=float(inference_cost or 0.0),
            llm_calls=int(llm_calls or 0),
            agents=agents_by_topic.get(topic.id, []),
            users=users_by_topic.get(topic.id, []),
            teams=teams_by_topic.get(topic.id, []),
            documents=documents_by_topic.get(topic.id, []),
        )
        for topic, inference_cost, llm_calls in topic_rows
    ]
    return TopicPage(
        items=items,
        total=total,
        month=normalized_month,
        available_months=await _available_usage_months(
            normalized_month,
            timezone_name=timezone_name,
            agent_ids=agent_ids,
        ),
    )


async def list_for_conversation(
    *, connection_id: int, room_id: str
) -> list[TopicRead]:
    """Derive one Messenger room's Topics from messages and inherited Tasks."""

    from app.messenger import Message, Room
    from app.task import Task

    topic_ids = union_all(
        select(Task.topic_id.label("topic_id")).where(
            Task.messenger_connection_id == connection_id,
            Task.message_group_id == room_id,
            Task.topic_id.is_not(None),
        ),
        select(Message.topic_id.label("topic_id")).where(
            Message.connection_id == connection_id,
            Message.room_id == room_id,
            Message.topic_id.is_not(None),
        ),
        select(Room.topic_id.label("topic_id")).where(
            Room.connection_id == connection_id,
            Room.external_id == room_id,
            Room.topic_id.is_not(None),
        ),
    ).subquery()
    result = await get_db().execute(
        Topic.histo_filter(
            select(Topic)
            .join(topic_ids, topic_ids.c.topic_id == Topic.id)
            .distinct()
        ).order_by(Topic.updated_at.desc().nullslast(), Topic.created_at.desc())
    )
    return [_read(topic) for topic in result.scalars()]


async def get(topic_id: UUID) -> TopicRead | None:
    topic = await get_db().scalar(
        Topic.histo_filter(select(Topic).where(Topic.id == topic_id))
    )
    return _read(topic) if topic is not None else None


__all__ = [
    "TopicConflictError",
    "TopicNotFoundError",
    "create",
    "create_from_classification",
    "delete_topic",
    "get",
    "get_content",
    "list_candidates",
    "list_for_conversation",
    "list_keywords",
    "list_linked_memories",
    "list_linked_memories_in_scope",
    "list_page",
    "list_refs",
    "merge",
    "prefer_reuse",
    "project_memory",
    "resolve_classification",
    "split",
    "update_topic",
]
