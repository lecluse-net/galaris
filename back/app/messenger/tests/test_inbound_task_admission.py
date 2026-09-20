from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import ResourceClosedError

from app.messenger import facade, inbound, journal, service
from app.messenger.events import Signal
from app.messenger._observations import (
    ObservedMessengerMessage,
    ObservedMessengerUser,
)
from app.messenger.interface import BridgeSpec


def _message() -> ObservedMessengerMessage:
    return ObservedMessengerMessage(
        id="9:42",
        platform="mail",
        tool_id=3,
        recipient=ObservedMessengerUser(
            id="agent@example.org",
            connection_id=7,
            tool_id=3,
        ),
        text="Read with mail_get.",
    )


def _stored(status: str = "accepted", platform: str = "mail") -> SimpleNamespace:
    return SimpleNamespace(
        platform=platform,
        direction="inbound",
        created_at=datetime.now(timezone.utc),
        status=status,
        tool_id=3,
        connection_id=7,
        remote_message_id="9:42",
    )


@pytest.mark.asyncio
async def test_task_only_inbound_is_marked_admitted_after_task_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted = AsyncMock()
    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(journal, "persist_inbound", AsyncMock(return_value=True))
    monkeypatch.setattr(
        journal,
        "stored_message",
        AsyncMock(return_value=_stored()),
    )
    monkeypatch.setattr(journal, "update_inbound_admission_status", update_status)
    monkeypatch.setattr(
        facade,
        "get_spec",
        lambda _kind: BridgeSpec(kind="mail", inbound_admission="task"),
    )
    monkeypatch.setattr(service, "admit_incoming", admitted)

    assert await inbound.dispatch_incoming(_message()) is True

    admitted.assert_awaited_once()
    update_status.assert_awaited_once_with(
        connection_id=7,
        remote_message_id="9:42",
        status="admitted",
    )


@pytest.mark.asyncio
async def test_failed_task_admission_is_retried_for_a_journal_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted = AsyncMock()
    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(journal, "persist_inbound", AsyncMock(return_value=False))
    monkeypatch.setattr(
        journal,
        "stored_message",
        AsyncMock(return_value=_stored("failed")),
    )
    monkeypatch.setattr(journal, "update_inbound_admission_status", update_status)
    monkeypatch.setattr(
        facade,
        "get_spec",
        lambda _kind: BridgeSpec(kind="mail", inbound_admission="task"),
    )
    monkeypatch.setattr(service, "admit_incoming", admitted)

    assert await inbound.dispatch_incoming(_message()) is True

    admitted.assert_awaited_once()
    update_status.assert_awaited_once_with(
        connection_id=7,
        remote_message_id="9:42",
        status="admitted",
    )


@pytest.mark.asyncio
async def test_failed_task_admission_keeps_message_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(journal, "persist_inbound", AsyncMock(return_value=True))
    monkeypatch.setattr(
        journal,
        "stored_message",
        AsyncMock(return_value=_stored()),
    )
    monkeypatch.setattr(journal, "update_inbound_admission_status", update_status)
    monkeypatch.setattr(
        facade,
        "get_spec",
        lambda _kind: BridgeSpec(kind="mail", inbound_admission="task"),
    )
    monkeypatch.setattr(
        service,
        "admit_incoming",
        AsyncMock(side_effect=RuntimeError("task database unavailable")),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await inbound.dispatch_incoming(_message())

    update_status.assert_awaited_once_with(
        connection_id=7,
        remote_message_id="9:42",
        status="failed",
        error="RuntimeError",
    )


@pytest.mark.asyncio
async def test_stale_instant_history_is_blocked_before_business_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored(platform="nextcloud_talk")
    receiver = AsyncMock()
    signal = Signal("stale_history_must_not_emit")
    signal.connect(receiver)
    archive = AsyncMock(return_value=True)
    monkeypatch.setattr(inbound, "message_received", signal)
    monkeypatch.setattr(journal, "persist_inbound", AsyncMock(return_value=True))
    monkeypatch.setattr(journal, "stored_message", AsyncMock(return_value=stored))
    monkeypatch.setattr(service, "archive_stale_instant_message", archive)
    monkeypatch.setattr(
        facade,
        "get_spec",
        lambda _kind: BridgeSpec(kind="nextcloud_talk"),
    )

    assert await inbound.dispatch_incoming(_message()) is True

    archive.assert_awaited_once_with(stored)
    receiver.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_conversation_admission_is_retried_for_a_journal_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored(platform="nextcloud_talk")
    persist = AsyncMock(side_effect=[True, False, False])

    async def update_status(**values: object) -> bool:
        stored.status = str(values["status"])
        return True

    attempts = 0

    async def admit(_message: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ResourceClosedError("This transaction is closed")

    signal = Signal("retryable_conversation")
    signal.connect(admit)
    monkeypatch.setattr(inbound, "message_received", signal)
    monkeypatch.setattr(journal, "persist_inbound", persist)
    monkeypatch.setattr(journal, "stored_message", AsyncMock(return_value=stored))
    status_update = AsyncMock(side_effect=update_status)
    monkeypatch.setattr(journal, "update_inbound_admission_status", status_update)
    monkeypatch.setattr(
        facade,
        "get_spec",
        lambda _kind: BridgeSpec(kind="nextcloud_talk"),
    )
    inbound._reset_dedup_for_tests()  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ResourceClosedError, match="transaction is closed"):
        await inbound.dispatch_incoming(_message())

    assert stored.status == "failed"
    assert await inbound.dispatch_incoming(_message()) is True
    assert stored.status == "admitted"
    assert await inbound.dispatch_incoming(_message()) is False
    assert attempts == 2
    assert [call.kwargs["status"] for call in status_update.await_args_list] == [
        "failed",
        "admitted",
    ]
    assert status_update.await_args_list[0].kwargs["error"] == "ResourceClosedError"


@pytest.mark.asyncio
async def test_conversation_without_receiver_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored(platform="nextcloud_talk")
    monkeypatch.setattr(inbound, "message_received", Signal("no_receiver"))
    monkeypatch.setattr(journal, "persist_inbound", AsyncMock(return_value=True))
    monkeypatch.setattr(journal, "stored_message", AsyncMock(return_value=stored))
    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(journal, "update_inbound_admission_status", update_status)
    monkeypatch.setattr(
        facade,
        "get_spec",
        lambda _kind: BridgeSpec(kind="nextcloud_talk"),
    )

    with pytest.raises(RuntimeError, match="no registered receiver"):
        await inbound.dispatch_incoming(_message())

    update_status.assert_not_awaited()
