"""Process human activities use the same canonical messaging path on every transport."""

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from app.connection import Connection

from app.file_share import ResourceContext, resource_info
from app.messenger import (ChoiceRequest, ChoiceOption, ChoiceResolution, PendingChoice, register_choice_handler, apply_interpreted_response, create_choice,
    messenger_for_agent_connection, request_user_choice, list_pending_choices, expire_user_choice, Room, Message, MessengerUser)
from app.process import ProcessHumanContact, ProcessHumanRequest
from app.process.facade import complete_human_activity, human_activity_pending, normalize_human_reply, ValueContractError
from app.tools import RecoverableToolError
from core.i18n import current_language, t
from core.database import get_db
from core.user import get_user_record

from .contracts import ConversationTurn
from .models import ConversationProcessLink, ConversationRound, ConversationRoundMessage


PROCESS_HUMAN_INTERACTION = "process_human_activity"


class ProcessHumanMessenger:
    def __init__(self) -> None:
        register_choice_handler(PROCESS_HUMAN_INTERACTION, self.choose)

    async def requester(self, run_id: UUID, agent_id: int) -> int | None:
        return await get_db().scalar(select(ConversationRound.requester_user_id)
            .join(ConversationProcessLink, ConversationProcessLink.round_id == ConversationRound.id)
            .join(Room, Room.id == ConversationRound.room_id)
            .join(Connection, Connection.id == Room.connection_id)
            .where(ConversationProcessLink.process_run_id == run_id,
                Connection.agent_id == agent_id, ConversationRound.requester_user_id.is_not(None))
            .order_by(ConversationRound.created_at).limit(1))

    @staticmethod
    async def choose(choice: PendingChoice, resolution: ChoiceResolution) -> None:
        if not choice.metadata.get("decision") or resolution.option_id not in {"true", "false"}:
            raise ValueError("A human IF requires an explicit True or False choice")
        await complete_human_activity(UUID(str(choice.metadata["attempt_id"])),
            user_id=int(choice.metadata["assigned_user_id"]),
            output={"decision": {"type": "bool", "value": resolution.option_id == "true"}})

    async def withdraw(self, *, agent_id: int, attempt_id: UUID, question_id: UUID | None = None) -> None:
        await expire_user_choice(agent_id=agent_id, kind=PROCESS_HUMAN_INTERACTION,
            idempotency_key=f"process-human:{question_id or attempt_id}")

    async def deliver(self, request: ProcessHumanRequest, contact: ProcessHumanContact | None) -> None:
        user = await get_user_record(request.user_id)
        if user is None or not user.is_active:
            raise PermissionError("The assigned human is inactive")
        if not await human_activity_pending(request.attempt_id, question_id=request.question_id):
            return
        language = await current_language(user_id=request.user_id)
        choice = ChoiceRequest(kind=PROCESS_HUMAN_INTERACTION, title=request.title,
            body=request.instructions if request.decision else request.instructions + "\n\n" + t("process.human.messaging_reply", language),
            options=[ChoiceOption(id="true", label="True"), ChoiceOption(id="false", label="False")] if request.decision else [],
            free_text=not request.decision, interpretation_required=not request.decision,
            timeout_seconds=10 * 365 * 24 * 3600, language=language,
            metadata={"attempt_id": str(request.attempt_id), "run_id": str(request.run_id),
                "assigned_user_id": request.user_id, "input": request.input,
                "outputs": request.outputs, "files": request.files, "decision": request.decision,
                "question_id": str(request.question_id) if request.question_id is not None else None})
        key = f"process-human:{request.question_id or request.attempt_id}"
        origin = (await get_db().execute(select(Room, MessengerUser.external_id)
            .join(Connection, Connection.id == Room.connection_id)
            .join(ConversationRound, ConversationRound.room_id == Room.id)
            .join(ConversationProcessLink, ConversationProcessLink.round_id == ConversationRound.id)
            .join(ConversationRoundMessage, ConversationRoundMessage.round_id == ConversationRound.id)
            .join(Message, Message.id == ConversationRoundMessage.message_id)
            .join(MessengerUser, MessengerUser.id == Message.sender_messenger_user_id)
            .where(ConversationProcessLink.process_run_id == request.run_id,
                ConversationRoundMessage.role == "input", Message.requester_user_id == request.user_id,
                MessengerUser.galaris_user_id == request.user_id, MessengerUser.is_ai.is_(False),
                Connection.agent_id == request.agent_id,
                ConversationRound.requester_user_id == request.user_id, Room.deleted_at.is_(None))
            .order_by(ConversationRound.created_at, ConversationRoundMessage.sequence.desc()).limit(1))).first()
        if origin is not None:
            room, peer = origin
            messenger = await messenger_for_agent_connection(request.agent_id, room.connection_id)
            await create_choice(messenger, agent_id=request.agent_id, room_id=str(room.id), user_id=peer,
                request=choice, idempotency_key=key)
        elif contact is not None and contact.connection_id is not None and contact.external_user:
            messenger = await messenger_for_agent_connection(request.agent_id, contact.connection_id)
            room = await messenger.ensure_direct_room(contact.external_user)
            await create_choice(messenger, agent_id=request.agent_id, room_id=str(room.id),
                user_id=contact.external_user, request=choice, idempotency_key=key)
        else:
            await request_user_choice(agent_id=request.agent_id, user_id=request.user_id,
                request=choice, idempotency_key=key)


async def respond_to_process_activity(turn: ConversationTurn, reference: str,
                                      output: dict[str, Any], *, typed_values: bool = False) -> dict[str, Any]:
    """Recheck scope and file access, then commit the result with its messaging receipt."""
    if turn.sender_is_ai or (turn.messages and turn.messages[-1].get("sender_is_ai")):
        raise PermissionError("A human activity requires the assigned human's reply")
    scope = turn.messaging_context
    if not scope.get("connection_id") or not scope.get("participant_id"):
        raise PermissionError("The conversation has no authenticated messaging participant")

    normalized: dict[str, Any] = {}

    def normalize_response(choice: PendingChoice, response: dict[str, Any]) -> dict[str, Any]:
        try:
            normalized.update(normalize_human_reply(choice.metadata.get("outputs"), response,
                typed_values=typed_values))
        except ValueContractError as exc:
            raise RecoverableToolError(str(exc)) from exc
        return normalized

    async def apply(choice: PendingChoice) -> None:
        if scope.get("requester_user_id") != choice.metadata["assigned_user_id"]:
            raise PermissionError("This message is not authenticated as the assigned human")
        # Check every nested file value, including arrays and object outputs. Only
        # canonical references travel into the Process; media bytes stay at the Tool.
        pending: list[Any] = list(normalized.values())
        while pending:
            value: Any = pending.pop()
            if isinstance(value, dict):
                record = cast(dict[str, Any], value)
                if record.get("type") == "File" and record.get("value") is not None:
                    await resource_info(ResourceContext(agent_id=turn.agent_id, runtime="internal",
                        conversation_turn=turn), record["value"])
                else:
                    pending.extend(record.values())
            elif isinstance(value, list):
                pending.extend(cast(list[Any], value))
        await complete_human_activity(UUID(str(choice.metadata["attempt_id"])),
            user_id=int(choice.metadata["assigned_user_id"]), output=normalized,
            question_id=UUID(str(choice.metadata["question_id"])) if choice.metadata.get("question_id") else None)

    applied = await apply_interpreted_response(reference=reference, kind=PROCESS_HUMAN_INTERACTION,
        agent_id=turn.agent_id, connection_id=int(str(scope["connection_id"])),
        tool_id=int(str(scope["tool_id"])) if scope.get("tool_id") is not None else None,
        room_id=str(turn.room_id), user_id=str(scope["participant_id"]), response=output, apply=apply,
        normalize_response=normalize_response)
    return {"completed": True, "applied": applied, "reference": reference.strip().lstrip("#").upper()}


def process_interaction_context(metadata: dict[str, Any]) -> str:
    """Bound the JSON presented to the model; full declarations remain tool-readable."""
    return json.dumps({key: metadata.get(key) for key in ("input", "outputs", "files")},
        ensure_ascii=False)[:12_000]


async def pending_process_activities(turn: ConversationTurn, page: int = 1) -> dict[str, Any]:
    scope = turn.messaging_context
    if page < 1 or not scope.get("connection_id") or not scope.get("participant_id") or turn.sender_is_ai:
        raise ValueError("An authenticated conversation participant and a positive page are required")
    choices = await list_pending_choices(agent_id=turn.agent_id,
        connection_id=int(str(scope["connection_id"])),
        tool_id=int(str(scope["tool_id"])) if scope.get("tool_id") is not None else None,
        room_id=str(turn.room_id), user_id=str(scope["participant_id"]),
        kind=PROCESS_HUMAN_INTERACTION, limit=20, offset=(page - 1) * 20)
    requester = scope.get("requester_user_id")
    live = await live_process_choices(choices, requester_user_id=requester if isinstance(requester, int) else None)
    return {"page": page, "has_more": len(choices) == 20, "items": [
        {"reference": item.reference, "title": item.title, "instructions": item.body,
            **{key: item.metadata.get(key) for key in ("input", "outputs", "files")}} for item in live]}


async def live_process_choices(choices: list[PendingChoice], *, requester_user_id: int | None) -> list[PendingChoice]:
    live: list[PendingChoice] = []
    for choice in choices:
        if choice.kind == PROCESS_HUMAN_INTERACTION:
            if choice.metadata.get("assigned_user_id") != requester_user_id:
                continue
            question_id = UUID(str(choice.metadata["question_id"])) if choice.metadata.get("question_id") else None
            if not await human_activity_pending(UUID(str(choice.metadata["attempt_id"])), question_id=question_id):
                continue
        live.append(choice)
    return live
