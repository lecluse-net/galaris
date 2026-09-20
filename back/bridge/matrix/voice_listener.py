"""Auto-answer valid incoming Matrix VoIP invites for voice-enabled agents."""

from __future__ import annotations

import asyncio
import time
import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.agent.models import Agent
from app.connection.models import Connection
from app.voice.call_manager import voice_call_manager
from core.params import runtime_settings
from core.database import get_db_session
from core.util import as_dict

from .client import Matrix
from .events import MatrixRoomEvent, matrix_event_bus

_RECONCILE_INTERVAL = 2.0
_listener_tasks: dict[int, asyncio.Task[None]] = {}
_listener_signatures: dict[int, tuple[tuple[str, str], ...]] = {}
_supervisor: asyncio.Task[None] | None = None


def _configuration_signature() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (name, str(value))
            for name, value in runtime_settings.model_dump().items()
            if name.startswith("VOICE_")
            or name.startswith("MESSENGER_MATRIX_")
        )
    )


async def _discover_connections() -> dict[int, int]:
    if (
        not runtime_settings.VOICE_ENABLED
        or not runtime_settings.VOICE_AUTO_ANSWER_ENABLED
    ):
        return {}
    from app.agent import list_driver_specs
    from app.messenger import messaging_tool_records
    from app.tools import tool_service

    voice_drivers = tuple(
        spec.code for spec in list_driver_specs() if spec.tool_profile.voice_calling
    )
    if not voice_drivers:
        return {}
    async with get_db_session() as db:
        messenger_tools = await messaging_tool_records("matrix")
        tool_ids = [int(tool.id) for tool in messenger_tools]
        voice_tool = await tool_service.get_tool_record("voice")
        if not tool_ids or voice_tool is None:
            return {}
        voice_connection = aliased(Connection)
        rows = await db.execute(
            select(Connection.id, Connection.agent_id)
            .join(Agent, Agent.id == Connection.agent_id)
            .join(voice_connection, voice_connection.agent_id == Connection.agent_id)
            .where(
                Connection.tool_id.in_(tool_ids),
                Connection.active.is_(True),
                voice_connection.tool_id == voice_tool.id,
                voice_connection.active.is_(True),
                Agent.agent_driver.in_(voice_drivers),
            )
            .order_by(Connection.id)
        )
        return {
            int(connection_id): int(agent_id)
            for connection_id, agent_id in rows.all()
        }


async def _reconcile() -> None:
    discovered = await _discover_connections()
    signature = _configuration_signature()
    for connection_id, task in list(_listener_tasks.items()):
        if (
            connection_id in discovered
            and not task.done()
            and _listener_signatures.get(connection_id) == signature
        ):
            continue
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        _listener_tasks.pop(connection_id, None)
        _listener_signatures.pop(connection_id, None)
    for connection_id in sorted(set(discovered) - set(_listener_tasks)):
        _listener_tasks[connection_id] = asyncio.create_task(
            _run_connection(connection_id, discovered[connection_id]),
            name=f"matrix_voice_listener:{connection_id}",
        )
        _listener_signatures[connection_id] = signature
        logger.info("Matrix voice listener started connection={}", connection_id)


async def _supervise() -> None:
    while True:
        try:
            await asyncio.sleep(_RECONCILE_INTERVAL)
            await _reconcile()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Matrix voice listener reconciliation failed")


async def start_matrix_voice_listeners() -> None:
    global _supervisor
    if _supervisor is not None and not _supervisor.done():
        return
    await _reconcile()
    _supervisor = asyncio.create_task(_supervise(), name="matrix_voice_supervisor")


def voice_listeners_running() -> bool:
    """Return whether the Matrix voice reconciliation loop is alive."""
    return _supervisor is not None and not _supervisor.done()


async def stop_matrix_voice_listeners() -> None:
    global _supervisor
    if _supervisor is not None:
        _supervisor.cancel()
        await asyncio.gather(_supervisor, return_exceptions=True)
        _supervisor = None
    for task in _listener_tasks.values():
        task.cancel()
    if _listener_tasks:
        await asyncio.gather(*_listener_tasks.values(), return_exceptions=True)
    _listener_tasks.clear()
    _listener_signatures.clear()


def _valid_invite(event: MatrixRoomEvent, self_id: str) -> bool:
    content = event.content
    if event.type != "m.call.invite" or event.sender == self_id:
        return False
    if str(content.get("version") or "") != "1":
        return False
    invitee = str(content.get("invitee") or "")
    if invitee and invitee != self_id:
        return False
    offer = as_dict(content.get("offer"))
    if offer.get("type") != "offer" or not offer.get("sdp"):
        return False
    try:
        lifetime = max(0, int(content.get("lifetime") or 0))
        age = max(
            int((time.time() * 1_000) - event.origin_server_ts),
            int(as_dict(event.raw.get("unsigned")).get("age") or 0),
        )
    except (TypeError, ValueError):
        return False
    return bool(content.get("call_id") and lifetime and age <= lifetime)


async def _reject_invite(
    matrix: Matrix,
    event: MatrixRoomEvent,
    *,
    reason: str,
) -> None:
    await matrix.send_room_event(
        event.room_id,
        "m.call.reject",
        {
            "call_id": str(event.content.get("call_id") or ""),
            "party_id": uuid.uuid4().hex,
            "version": "1",
            "reason": reason,
        },
    )


async def _answer_invite(
    matrix: Matrix,
    event: MatrixRoomEvent,
    *,
    connection_id: int,
    agent_id: int,
) -> None:
    if not _valid_invite(event, matrix.user_id):
        return
    if await matrix.room_is_encrypted(event.room_id):
        logger.warning(
            "Matrix voice ignored encrypted room connection={} room={}",
            connection_id,
            event.room_id,
        )
        return
    members = await matrix.joined_members(event.room_id)
    if set(members) != {matrix.user_id, event.sender}:
        logger.warning(
            "Matrix voice ignored non-1:1 room connection={} room={}",
            connection_id,
            event.room_id,
        )
        await _reject_invite(matrix, event, reason="user_hangup")
        return
    if any(
        call.connection_id == connection_id and call.room_id == event.room_id
        for call in voice_call_manager.active_calls(agent_id=agent_id)
    ):
        await _reject_invite(matrix, event, reason="user_busy")
        return
    from .call import MatrixCall

    async with get_db_session():
        transport = await MatrixCall.from_connection_id(
            connection_id,
            outgoing=False,
            initial_event=event,
        )
    info, created = voice_call_manager.start_agent_call(
        agent_id=agent_id,
        connection_id=connection_id,
        room_id=event.room_id,
        transport=transport,
        remote_user_ids=(event.sender,),
    )
    if created:
        logger.info("Matrix voice auto-answer started call_id={}", info.call_id)


async def _run_connection(connection_id: int, agent_id: int) -> None:
    matrix: Matrix | None = None
    subscription = matrix_event_bus.subscribe(connection_id)
    try:
        async with get_db_session():
            matrix = await Matrix.from_connection_id(connection_id)
        while True:
            event = await subscription.get()
            try:
                await _answer_invite(
                    matrix,
                    event,
                    connection_id=connection_id,
                    agent_id=agent_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Matrix voice could not process invite connection={}", connection_id
                )
    finally:
        await subscription.close()
        if matrix is not None:
            await matrix.aclose()
