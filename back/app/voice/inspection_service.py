"""Complete administrative projection for one audio conversation round."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agent import Agent
from app.conversation import ConversationRound
from app.llm import LLMCall, llm_call_service
from core.database import get_db

from .models import VoiceConversationSession
from .monitoring_service import get_turn


async def inspect_turn(turn_id: UUID) -> dict[str, Any] | None:
    """Return the canonical round, session, agent, and correlated LLM calls."""

    detail = await get_turn(turn_id)
    if detail is None:
        return None
    db = get_db()
    round_ = await db.get(ConversationRound, turn_id)
    session = await db.get(VoiceConversationSession, detail.session_id)
    if round_ is None or session is None:
        return None
    calls = list(
        (
            await db.scalars(
                select(LLMCall)
                .where(LLMCall.conversation_round_id == turn_id)
                .order_by(LLMCall.started_at.asc(), LLMCall.id.asc())
            )
        ).all()
    )
    serialized_calls = await llm_call_service.serialize_calls(calls)
    agent = await db.get(Agent, detail.agent_id) if detail.agent_id is not None else None
    return {
        "turn": detail.model_dump(mode="json"),
        "session": {
            "id": str(session.id),
            "revision": session.revision,
            "messenger_room_id": str(session.messenger_room_id),
            "status": session.status,
            "next_sequence": session.next_sequence,
            "error": session.error,
            "started_at": session.started_at.isoformat(),
            "finished_at": (
                session.finished_at.isoformat()
                if session.finished_at is not None
                else None
            ),
        },
        "agent": (
            {
                "id": agent.id,
                "code": agent.code,
                "first_name": agent.first_name,
                "last_name": agent.last_name,
                "job_title": agent.job_title,
                "personality": agent.personality,
                "job_description": agent.job_description,
                "driver": agent.agent_driver,
            }
            if agent is not None
            else None
        ),
        "llm_calls": [item.model_dump(mode="json") for item in serialized_calls],
    }


__all__ = ["inspect_turn"]
