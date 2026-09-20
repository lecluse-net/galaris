"""Dream entry points that classify durable activities before memory work."""

from __future__ import annotations

from app.llm import model_usages

from typing import Any, Literal, cast as type_cast
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import String, cast, exists, func, or_, select

from app.conversation import ConversationTaskLink
from app.messenger import (
    ChoiceOption,
    ChoiceRequest,
    ChoiceResolution,
    MessengerFacade,
    PendingChoice,
    create_choice,
    messenger_for_agent_connection,
    register_choice_handler,
    resolve_task_messaging,
    Message,
)
from app.task import Task, TaskStatus
from app.topic import TopicCandidate, TopicClassification, service as topic_service
from app.topic.classifier import classify
from core.database import get_db, get_db_session
from core.i18n import render_prompt, t
from core.params import runtime_settings

from ..contracts import DreamClaim, DreamPrepared
from ..language import source_language, task_language
from ..models import DreamReceipt
from ..service import (
    claim_replayable_topic_application,
    claim_retry,
    create_running_receipt,
    replayable_topic_application,
)
from .task_memory import safe_memory_text


TopicCreationMode = Literal["forbid", "propose", "auto"]
TOPIC_APPROVAL_INTERACTION = "topic_creation_approval"
_APPROVAL_TIMEOUT_SECONDS = 7 * 24 * 60 * 60


def _task_activity(task: Task) -> str:
    result = task.get_execution_result()
    sections = (
        f"Label: {safe_memory_text(task.label)}",
        f"Objective: {safe_memory_text(task.objective)}",
        f"Outcome: {safe_memory_text(result.result if result else '')}",
        f"Feedback: {safe_memory_text(task.feedback)}",
        f"Error: {safe_memory_text(task.last_error)}",
    )
    return "\n\n".join(
        section for section in sections if not section.endswith(": ")
    )[:20_000]


def topic_creation_mode() -> TopicCreationMode:
    return runtime_settings.DREAM_TOPIC_CREATION_MODE


def topic_classification_payload(
    decision: TopicClassification,
    candidates: list[TopicCandidate],
    *,
    language: str,
    creation_mode: TopicCreationMode,
) -> dict[str, Any]:
    if decision.action == "create" and decision.topic_id is None:
        decision = decision.model_copy(update={"topic_id": uuid4()})
    candidate_ids = [candidate.id for candidate in candidates]
    if decision.action == "reuse" and decision.topic_id not in candidate_ids:
        assert decision.topic_id is not None
        candidate_ids.append(decision.topic_id)
    return {
        "decision": decision.model_dump(mode="json"),
        "candidate_ids": [str(topic_id) for topic_id in candidate_ids],
        "candidate_options": [
            {"topic_id": str(candidate.id), "title": candidate.title}
            for candidate in candidates[:3]
        ],
        "language": source_language(language),
        "creation_mode": creation_mode,
    }


def _allowed_topic_ids(payload: dict[str, Any]) -> set[UUID]:
    raw_values: object = payload.get("candidate_ids", [])
    if not isinstance(raw_values, list):
        return set()
    allowed: set[UUID] = set()
    for value in type_cast(list[object], raw_values):
        try:
            allowed.add(UUID(str(value)))
        except ValueError:
            continue
    return allowed


async def _assign_classification(
    *,
    payload: dict[str, Any],
    subject: Task | Message,
    decision: TopicClassification | None = None,
) -> int:
    if subject.topic_id is not None:
        return 0
    resolved_decision = decision or TopicClassification.model_validate(
        payload["decision"]
    )
    if isinstance(subject, Task):
        subject_language = task_language(subject)
    else:
        subject_language = source_language(payload.get("language"))
    topic = await topic_service.resolve_classification(
        resolved_decision,
        allowed_topic_ids=_allowed_topic_ids(payload),
        language=source_language(payload.get("language") or subject_language),
    )
    subject.topic_id = topic.id
    await get_db().commit()
    if isinstance(subject, Message):
        from .sequential_topic_classification import propagate_classified_subject

        await propagate_classified_subject(subject)
    return 1


def _approval_message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"dream.topic_approval.{key}", language), **values)


def _candidate_options(
    payload: dict[str, Any], *, language: str
) -> list[ChoiceOption]:
    raw_options_value: object = payload.get("candidate_options", [])
    if not isinstance(raw_options_value, list):
        return []
    allowed = _allowed_topic_ids(payload)
    options: list[ChoiceOption] = []
    for raw_value in type_cast(list[object], raw_options_value):
        if not isinstance(raw_value, dict):
            continue
        raw = type_cast(dict[str, object], raw_value)
        try:
            topic_id = UUID(str(raw.get("topic_id") or ""))
        except ValueError:
            continue
        title = str(raw.get("title") or "").strip()
        if topic_id not in allowed or not title:
            continue
        options.append(
            ChoiceOption(
                id=f"reuse:{topic_id}",
                label=_approval_message(
                    language, "reuse_option", title=safe_memory_text(title)
                ),
            )
        )
    return options


async def _approval_route(
    subject: Task | Message,
) -> tuple[MessengerFacade, int, str, str | None, str | None] | None:
    if isinstance(subject, Task):
        if subject.ai or not subject.message_group_id:
            return None
        messenger, _self_id = await resolve_task_messaging(subject)
        if messenger is None:
            return None
        data = subject.data if isinstance(subject.data, dict) else {}
        user_id = str(
            data.get("sender.user_id") or data.get("user_id") or ""
        ).strip() or None
        reply_to = str(data.get("message_id") or "").strip() or None
        assert subject.agent_id is not None
        return messenger, subject.agent_id, subject.message_group_id, user_id, reply_to

    if not subject.messenger_room_id or not subject.user_id:
        return None
    from app.connection import Connection

    connection = await get_db().get(Connection, subject.connection_id)
    if connection is None:
        return None
    try:
        messenger = await messenger_for_agent_connection(
            connection.agent_id, subject.connection_id
        )
    except ValueError:
        return None
    return (
        messenger,
        connection.agent_id,
        str(subject.messenger_room_id),
        subject.user_id if subject.direction == "inbound" else None,
        subject.remote_message_id if subject.direction == "inbound" else None,
    )


async def _request_topic_approval(
    *,
    claim: DreamClaim,
    payload: dict[str, Any],
    subject: Task | Message,
) -> int:
    route = await _approval_route(subject)
    if route is None:
        logger.warning(
            "Topic creation proposal cannot reach a human subject={}:{}",
            claim.subject_kind,
            claim.subject_id,
        )
        return 0
    messenger, agent_id, room_id, user_id, reply_to = route
    decision = TopicClassification.model_validate(payload["decision"])
    if decision.action != "create":
        raise ValueError("Only Topic creation decisions require approval.")
    language = source_language(payload.get("language"))
    description = safe_memory_text(decision.description) or _approval_message(
        language, "no_description"
    )
    keywords = ", ".join(safe_memory_text(value) for value in decision.keywords)
    body = _approval_message(
        language,
        "body",
        title=safe_memory_text(decision.title),
        description=description,
        keywords=keywords or _approval_message(language, "no_keywords"),
    )
    options = [
        ChoiceOption(
            id="create",
            label=_approval_message(language, "create_option"),
            aliases=["create", "créer", "creer", "approve", "approuver"],
        ),
        *_candidate_options(payload, language=language),
        ChoiceOption(
            id="reject",
            label=_approval_message(language, "reject_option"),
            aliases=["reject", "refuser", "deny", "non", "no"],
        ),
    ]
    await create_choice(
        messenger,
        agent_id=agent_id,
        room_id=room_id,
        user_id=user_id,
        request=ChoiceRequest(
            kind=TOPIC_APPROVAL_INTERACTION,
            title=_approval_message(language, "title"),
            body=body,
            options=options,
            metadata={
                "subject_kind": claim.subject_kind,
                "subject_id": claim.subject_id,
                "topic_payload": payload,
            },
            timeout_seconds=_APPROVAL_TIMEOUT_SECONDS,
            language=language,
        ),
        reply_to=reply_to,
        idempotency_key=f"topic-approval:{claim.receipt_id}",
    )
    return 1


async def apply_topic_classification(
    *,
    claim: DreamClaim,
    payload: dict[str, Any],
    subject: Task | Message,
) -> int:
    if subject.topic_id is not None:
        return 0
    decision = TopicClassification.model_validate(payload["decision"])
    if decision.action == "reuse":
        return await _assign_classification(payload=payload, subject=subject)
    mode = type_cast(
        TopicCreationMode,
        str(payload.get("creation_mode") or "propose"),
    )
    if mode == "forbid":
        return 0
    if mode == "propose":
        return await _request_topic_approval(
            claim=claim, payload=payload, subject=subject
        )
    if mode != "auto":
        raise ValueError(f"Unsupported Topic creation mode: {mode}")
    return await _assign_classification(payload=payload, subject=subject)


async def _handle_topic_approval(
    interaction: PendingChoice, resolution: ChoiceResolution
) -> None:
    raw_payload = interaction.metadata.get("topic_payload")
    if not isinstance(raw_payload, dict):
        logger.warning("Topic approval {} has no prepared payload", interaction.id)
        return
    payload = dict(type_cast(dict[str, Any], raw_payload))
    option_id = resolution.option_id or ""
    if option_id == "reject":
        logger.info("Topic creation rejected through interaction {}", interaction.id)
        return

    original = TopicClassification.model_validate(payload["decision"])
    if option_id == "create":
        if original.action != "create":
            logger.warning("Topic approval {} no longer contains a creation", interaction.id)
            return
        decision = original
    elif option_id.startswith("reuse:"):
        try:
            topic_id = UUID(option_id.removeprefix("reuse:"))
        except ValueError:
            logger.warning("Topic approval {} selected an invalid Topic", interaction.id)
            return
        if topic_id not in _allowed_topic_ids(payload):
            logger.warning("Topic approval {} selected an untrusted Topic", interaction.id)
            return
        decision = TopicClassification(
            action="reuse",
            topic_id=topic_id,
            confidence=1.0,
            reason="Selected by the human approver.",
        )
    else:
        logger.warning("Topic approval {} has an unsupported choice", interaction.id)
        return

    raw_subject_id = str(interaction.metadata.get("subject_id") or "")
    try:
        subject_id = UUID(raw_subject_id)
    except ValueError:
        logger.warning("Topic approval {} has an invalid subject", interaction.id)
        return
    subject_kind = str(interaction.metadata.get("subject_kind") or "")
    if subject_kind == "task":
        subject = await get_db().get(Task, subject_id)
    elif subject_kind == "message":
        subject = await get_db().get(Message, subject_id)
    else:
        logger.warning("Topic approval {} has an unknown subject kind", interaction.id)
        return
    if subject is None:
        return
    try:
        await _assign_classification(
            payload=payload,
            subject=subject,
            decision=decision,
        )
    except (LookupError, ValueError):
        logger.warning("Topic approval {} became stale before application", interaction.id)


class TaskTopicClassificationMechanism:
    key = "topic.classify_task"

    async def is_available(self) -> bool:
        async with get_db_session():
            from app.llm import profile_service

            return await profile_service.has_any_profile_value(model_usages.DREAM)

    async def count_pending(self) -> int:
        async with get_db_session():
            scanned = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "task",
                    DreamReceipt.subject_id == cast(Task.id, String),
                )
            )
            needs_replay = exists(
                select(DreamReceipt.id).where(
                    DreamReceipt.mechanism_key == self.key,
                    DreamReceipt.subject_kind == "task",
                    DreamReceipt.subject_id == cast(Task.id, String),
                    replayable_topic_application(),
                )
            )
            return int(
                await get_db().scalar(
                    select(func.count(Task.id)).where(
                        Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                        Task.topic_id.is_(None),
                        ~exists(
                            select(ConversationTaskLink.task_id).where(
                                ConversationTaskLink.task_id == Task.id
                            )
                        ),
                        or_(~scanned, needs_replay),
                    )
                )
                or 0
            )

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        replay = await claim_replayable_topic_application(
            self.key,
            subject_kind="task",
            eligibility=exists(
                select(Task.id).where(
                    cast(Task.id, String) == DreamReceipt.subject_id,
                    Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                    Task.topic_id.is_(None),
                    ~exists(
                        select(ConversationTaskLink.task_id).where(
                            ConversationTaskLink.task_id == Task.id
                        )
                    ),
                )
            ),
        )
        if replay is not None:
            return replay
        async with get_db_session():
            task = await get_db().scalar(
                select(Task)
                .where(
                    Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                    Task.topic_id.is_(None),
                    ~exists(
                        select(ConversationTaskLink.task_id).where(
                            ConversationTaskLink.task_id == Task.id
                        )
                    ),
                    ~exists(
                        select(DreamReceipt.id).where(
                            DreamReceipt.mechanism_key == self.key,
                            DreamReceipt.subject_kind == "task",
                            DreamReceipt.subject_id == cast(Task.id, String),
                        )
                    ),
                )
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
            if task is None:
                raise LookupError(f"Task {task_id} not found.")
            activity = _task_activity(task)
            candidates = await topic_service.list_candidates(
                activity=activity, limit=100
            )
            language = task_language(task)
            decision, cost = await classify(
                activity=activity,
                candidates=candidates,
                task_id=task_id,
                agent_id=task.agent_id,
                language=language,
            )
            decision, _reused_id = await topic_service.prefer_reuse(decision)
            return DreamPrepared(
                payload=topic_classification_payload(
                    decision,
                    candidates,
                    language=language,
                    creation_mode=topic_creation_mode(),
                ),
                cost=cost,
            )

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        async with get_db_session():
            task = await get_db().get(Task, UUID(claim.subject_id))
            if task is None:
                return 0
            return await apply_topic_classification(
                claim=claim, payload=payload, subject=task
            )


register_choice_handler(TOPIC_APPROVAL_INTERACTION, _handle_topic_approval)

task_topic_classification_mechanism = TaskTopicClassificationMechanism()

__all__ = [
    "TOPIC_APPROVAL_INTERACTION",
    "TaskTopicClassificationMechanism",
    "task_topic_classification_mechanism",
]
