"""Janus, the OpenAI-compatible entry agent that routes ``@agent-code`` sessions.

Each conversation moves directly from agent selection to routing. The selected agent is
recovered from the OpenAI message history when a client does not preserve ``conversation_id``.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional
from uuid import uuid4

from loguru import logger
from sqlalchemy import select

from core.database import get_db
from core.i18n import SUPPORTED_LANGUAGES, current_language, t
from app.agent.models import Agent
from .openai_schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChunkChoice,
    Choice,
    Message,
    ModelObject,
    Usage,
)
from .management_scope import current_management_scope
from .dialogue_service import current_dialogue_scope

# ──────────────────────────────────────────────────────────────────────────────

MODEL_ID = "janus"
SESSION_TTL = 3600

_sessions: Dict[str, "JanusSession"] = {}

_CODE_RE = re.compile(r'[@#]([\w][\w\-]*)')


# ──────────────────────────────────────────────────────────────────────────────
# Session
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class JanusSession:
    state: str = "SELECTING"          # SELECTING | ROUTING
    agent_code: Optional[str] = None
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.last_activity = datetime.now(timezone.utc)

    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.last_activity).total_seconds()
        return elapsed > SESSION_TTL

    def reset(self) -> None:
        """Return to agent selection."""
        self.state = "SELECTING"
        self.agent_code = None


def _get_session(session_key: str) -> JanusSession:
    session = _sessions.get(session_key)
    if session is None:
        session = JanusSession()
        _sessions[session_key] = session
    elif session.is_expired():
        logger.info("Janus: session {} expired; resetting", session_key[:8])
        session.reset()
    return session


# ──────────────────────────────────────────────────────────────────────────────
# Helpers DB
# ──────────────────────────────────────────────────────────────────────────────

async def _get_agents() -> list[Agent]:
    scope = await current_dialogue_scope()
    db = get_db()
    query = select(Agent).order_by(Agent.first_name)
    if scope.agent_ids is not None:
        query = query.where(Agent.id.in_(scope.agent_ids))
    result = await db.execute(query)
    return list(result.scalars().all())


async def _find_agent(query: str) -> tuple[Optional[Agent], list[Agent]]:
    """Resolve an agent code by exact match, unique prefix, then unique substring."""
    scope = await current_dialogue_scope()
    db = get_db()
    statement = select(Agent)
    if scope.agent_ids is not None:
        statement = statement.where(Agent.id.in_(scope.agent_ids))
    result = await db.execute(statement)
    all_agents: list[Agent] = list(result.scalars().all())

    normalized_query = query.casefold()

    # Exact match.
    for agent in all_agents:
        if agent.code and agent.code.casefold() == normalized_query:
            return agent, []

    # Unique prefix.
    starts = [
        e for e in all_agents if e.code and e.code.casefold().startswith(normalized_query)
    ]
    if len(starts) == 1:
        return starts[0], []
    if len(starts) > 1:
        return None, starts

    # Unique substring.
    contains = [
        e for e in all_agents if e.code and normalized_query in e.code.casefold()
    ]
    if len(contains) == 1:
        return contains[0], []
    if len(contains) > 1:
        return None, contains

    return None, []


async def _correlate_process_agent_call(
    *,
    raw_body: Dict[str, Any],
    target_agent_code: str,
) -> None:
    """Resolve and authorize Process provenance before Janus delegates."""
    raw_process_run_id = raw_body.get("galaris_process_run_id")
    workflow_id = raw_body.get("galaris_workflow_id")
    engine_run_id = raw_body.get("galaris_engine_run_id")
    if not raw_process_run_id and not (workflow_id and engine_run_id):
        return

    scope = await current_management_scope()
    from app.llm import resolve_runtime_process_run_id

    process_run_id = await resolve_runtime_process_run_id(
        raw_process_run_id=raw_process_run_id,
        workflow_id=workflow_id,
        engine_run_id=engine_run_id,
        task_id=None,
        agent_ids=scope.agent_ids,
    )
    if process_run_id is None:
        return
    raw_body["galaris_process_run_id"] = str(process_run_id)

    from app.process import process_service

    await process_service.record_inbound_call(
        process_run_id,
        kind="agent",
        target_code=target_agent_code,
        metadata={"correlation_id": raw_body.get("galaris_correlation_id")},
        agent_ids=scope.agent_ids,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Response formatting
# ──────────────────────────────────────────────────────────────────────────────

def _message(key: str, language: str, **values: str) -> str:
    return t(f"janus.{key}", language).format(**values)


def _agent_list_text(agents: list[Agent], language: str) -> str:
    lines = [_message("agent_list_heading", language) + "\n"]
    for agent in agents:
        name = f"{agent.first_name} {agent.last_name}".strip()
        line = f"• **@{agent.code}** — {name}"
        if agent.job_title:
            line += f" *({agent.job_title})*"
        lines.append(line)
    lines.append("\n" + _message("agent_list_instruction", language))
    return "\n".join(lines)


def _make_json(content: str, conversation_id: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid4().hex[:16]}",
        object="chat.completion",
        created=int(time.time()),
        model=MODEL_ID,
        choices=[Choice(index=0, message=Message(role="assistant", content=content), finish_reason="stop")],
        usage=Usage(),
        conversation_id=conversation_id,
    )


def _make_stream(content: str, conversation_id: str) -> AsyncIterator[str]:
    cid = f"chatcmpl-{uuid4().hex[:16]}"
    ts = int(time.time())

    async def gen() -> AsyncIterator[str]:
        for delta in ({"role": "assistant"}, {"content": content}, {}):
            finish = "stop" if not delta else None
            chunk = ChatCompletionChunk(
                id=cid, created=ts, model=MODEL_ID,
                choices=[ChunkChoice(index=0, delta=delta, finish_reason=finish)],
                conversation_id=conversation_id if delta.get("role") else None,
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return gen()


def _respond(content: str, conversation_id: str, stream: bool) -> Any:
    return _make_stream(content, conversation_id) if stream else _make_json(content, conversation_id)


def _message_text(message: Message) -> str:
    content = message.content
    if isinstance(content, list):
        return " ".join(str(segment.get("text", "")) for segment in content)
    return str(content or "")


def _is_janus_control_message(message: Message) -> bool:
    if message.role != "assistant":
        return False
    text = _message_text(message)
    keys = (
        "guide",
        "agent_list_heading",
        "choose_agent",
        "connected_marker",
        "session_reset",
        "several_match_marker",
        "not_found_marker",
    )
    control_markers = tuple(
        _message(key, language)
        for language in SUPPORTED_LANGUAGES
        for key in keys
    )
    return any(marker in text for marker in control_markers)


def _agent_segment_start(messages: list[Message], agent_code: str) -> int | None:
    start: int | None = None
    for index, message in enumerate(messages):
        if message.role != "user":
            continue
        match = _CODE_RE.search(_message_text(message))
        if match and match.group(1).casefold() == agent_code.casefold():
            start = index
    return start


def _messages_for_agent(
    messages: list[Message],
    *,
    agent_code: str,
    current_content_after_code: str,
) -> list[Message]:
    """Remove Janus selection dialogue from the history forwarded to an agent."""
    start = _agent_segment_start(messages, agent_code)
    segment = messages[start:] if start is not None else messages[-1:]
    delegated: list[Message] = []

    for message in segment:
        if _is_janus_control_message(message):
            continue

        if message.role == "user":
            text = _message_text(message)
            match = _CODE_RE.search(text)
            if match:
                if match.group(1).casefold() != agent_code.casefold():
                    continue
                content_after_code = text[match.end():].strip()
                if not content_after_code:
                    continue
                delegated.append(Message(role="user", content=content_after_code))
                continue

        delegated.append(message)

    if not delegated and current_content_after_code:
        delegated.append(Message(role="user", content=current_content_after_code))

    return delegated


def _agent_code_from_history(messages: list[Message]) -> str | None:
    """Return the latest explicit agent selection carried by OpenAI history."""

    for message in reversed(messages):
        if message.role != "user":
            continue
        match = _CODE_RE.search(_message_text(message))
        if match:
            return match.group(1)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

async def handle(
    request: ChatCompletionRequest,
    raw_body: Dict[str, Any],
    conversation_id: str,
) -> Any:
    from core.user import user_service
    session = _get_session(f"human:{user_service.get_current_user_id()}:{conversation_id}")
    session.touch()
    stream = request.stream
    language = await current_language()

    # Extract the most recent user message.
    last_user_msg = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            c = msg.content
            if isinstance(c, list):
                last_user_msg = " ".join(str(seg.get("text", "")) for seg in c)
            else:
                last_user_msg = str(c or "")
            break

    # Reset command.
    if last_user_msg.strip().lower() in ("/reset", "/restart"):
        session.reset()
        agents = await _get_agents()
        greeting = (
            _message("session_reset", language)
            + " "
            + _message("welcome", language)
            + "\n\n"
            + _message("guide", language)
            + "\n\n"
        )
        return _respond(greeting + _agent_list_text(agents, language), conversation_id, stream)

    # Detect an @code in the current message.
    code_match = _CODE_RE.search(last_user_msg)
    detected_code: Optional[str] = code_match.group(1) if code_match else None
    # Keep content after @code, or the complete message when no code is present.
    content_after_code = last_user_msg[code_match.end():].strip() if code_match else last_user_msg.strip()

    if detected_code:
        agent, candidates = await _find_agent(detected_code)
        if agent:
            switching = (session.agent_code != agent.code)
            session.state = "ROUTING"
            session.agent_code = agent.code
            if switching:
                logger.info("Janus: {} → @{}", conversation_id[:8], agent.code)

            if not content_after_code:
                name = f"{agent.first_name} {agent.last_name}".strip()
                msg = _message("connected", language, name=name, code=agent.code)
                return _respond(msg, conversation_id, stream)
            # Otherwise forward the remaining content to the agent.
        elif candidates:
            lines = [_message("several_match", language, code=detected_code) + "\n"]
            for c in candidates:
                lines.append(f"• @{c.code} — {c.first_name} {c.last_name}".strip())
            return _respond("\n".join(lines), conversation_id, stream)
        else:
            reply = _message("not_found", language, code=detected_code) + "\n\n"
            agents = await _get_agents()
            return _respond(reply + _agent_list_text(agents, language), conversation_id, stream)

    # Recover routing from the stateless OpenAI history. Some clients ignore the
    # conversation_id extension and would otherwise lose the selected agent on every turn.
    if session.state != "ROUTING":
        historical_code = _agent_code_from_history(list(request.messages))
        if historical_code:
            historical_agent, _ = await _find_agent(historical_code)
            if historical_agent is not None:
                session.state = "ROUTING"
                session.agent_code = historical_agent.code

    if session.state == "SELECTING":
        agents = await _get_agents()
        reply = (
            _message("welcome", language)
            + "\n\n"
            + _message("guide", language)
            + "\n\n"
            + _message("choose_agent", language)
            + "\n\n"
            + _agent_list_text(agents, language)
        )
        return _respond(reply, conversation_id, stream)

    # Forward to the active agent.

    if session.state == "ROUTING" and session.agent_code:
        agent, _ = await _find_agent(session.agent_code)
        if agent is None:
            missing_code = session.agent_code
            session.reset()
            agents = await _get_agents()
            reply = (
                _message("agent_missing", language, code=missing_code)
                + "\n\n"
                + _agent_list_text(agents, language)
            )
            return _respond(reply, conversation_id, stream)

        forwarded = request.model_copy(update={"model": agent.code})

        base_messages = _messages_for_agent(
            list(request.messages),
            agent_code=agent.code,
            current_content_after_code=content_after_code,
        )

        if base_messages:
            forwarded = forwarded.model_copy(update={"messages": base_messages})

        await _correlate_process_agent_call(
            raw_body=raw_body,
            target_agent_code=agent.code,
        )

        from .openai_service import run_local_chat_completion

        return await run_local_chat_completion(agent, forwarded, raw_body)

    # Fallback
    agents = await _get_agents()
    return _respond(_agent_list_text(agents, language), conversation_id, stream)


# ──────────────────────────────────────────────────────────────────────────────
# Model exposed by /api/janus/openai/models
# ──────────────────────────────────────────────────────────────────────────────

async def get_aliases() -> list[str]:
    """Return Janus aliases from application parameters."""
    from core.params import params_service, Params
    value = await params_service.get(Params.JANUS_ALIASES, "")
    if not value:
        return []
    return [a.strip() for a in value.split(",") if a.strip()]


def janus_model_object() -> ModelObject:
    return ModelObject(id=MODEL_ID, owned_by="galaris", created=0)


def alias_model_object(alias: str) -> ModelObject:
    return ModelObject(id=alias, owned_by="galaris", created=0)
