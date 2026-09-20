import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from bridge.mail import messenger
from bridge.mail.contracts import (
    MailConnectionConfig,
    MailEndpointConfig,
    MailMessageRef,
    MailMessageSummary,
    MailPollBatch,
)


def _config(*, poll_interval_s: float = 17) -> MailConnectionConfig:
    endpoint = MailEndpointConfig(
        host="mail.example.org",
        port=993,
        security="tls",
        username="agent@example.org",
        password=SecretStr("secret"),
    )
    return MailConnectionConfig(
        connection_id=7,
        agent_id=11,
        email_address="agent@example.org",
        imap=endpoint,
        smtp=endpoint.model_copy(update={"port": 465}),
        connect_timeout_s=10,
        operation_timeout_s=30,
        poll_interval_s=poll_interval_s,
        max_attachment_bytes=1_000,
        max_total_attachment_bytes=2_000,
    )


def _summary(uid: int) -> MailMessageSummary:
    ref = MailMessageRef(mailbox="INBOX", uid_validity=9, uid=uid)
    return MailMessageSummary(
        ref=ref.encode(),
        subject=f"Message {uid}",
        from_name="Alice Exemple",
        from_address="sender@example.org",
        to_addresses=["agent@example.org"],
        date=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )


def test_mail_cursor_is_versioned_and_rejects_invalid_values() -> None:
    encoded = messenger._encode_cursor(9, 42)  # pyright: ignore[reportPrivateUsage]

    assert messenger._decode_cursor(encoded) == (9, 42)  # pyright: ignore[reportPrivateUsage]
    assert messenger._decode_cursor('{"v":2}') is None  # pyright: ignore[reportPrivateUsage]
    assert messenger._decode_cursor("broken") is None  # pyright: ignore[reportPrivateUsage]


def test_mail_sender_exposes_display_name_and_stable_email_identity() -> None:
    observed = messenger.MailMessenger(_config(), tool_id=3)._message(_summary(41))  # pyright: ignore[reportPrivateUsage]

    assert observed.sender is not None
    assert observed.sender.id == "sender@example.org"
    assert observed.sender.display_name == "Alice Exemple"


@pytest.mark.asyncio
async def test_first_poll_establishes_baseline_and_uses_configured_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = messenger.MailMessenger(_config(), tool_id=3)
    state = AsyncMock()
    monkeypatch.setattr(messenger.journal, "listener_cursor", AsyncMock(return_value=None))
    monkeypatch.setattr(messenger.journal, "update_listener_state", state)
    monkeypatch.setattr(
        messenger.ImapClient,
        "poll_inbox",
        lambda _self, *, after_uid, limit: MailPollBatch(
            uid_validity=9,
            latest_uid=40,
        ),
    )

    async def stop_after_delay(delay: float) -> None:
        assert delay == 17
        raise asyncio.CancelledError

    monkeypatch.setattr(messenger.asyncio, "sleep", stop_after_delay)

    with pytest.raises(asyncio.CancelledError):
        await adapter.listen()

    state.assert_awaited_once_with(
        7,
        "mail",
        cursor=messenger._encode_cursor(9, 40),  # pyright: ignore[reportPrivateUsage]
        available=True,
    )


@pytest.mark.asyncio
async def test_poll_dispatches_new_uids_in_order_before_advancing_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = messenger.MailMessenger(_config(), tool_id=3)
    state = AsyncMock()
    dispatch = AsyncMock(return_value=True)
    monkeypatch.setattr(
        messenger.journal,
        "listener_cursor",
        AsyncMock(return_value=messenger._encode_cursor(9, 40)),  # pyright: ignore[reportPrivateUsage]
    )
    monkeypatch.setattr(messenger.journal, "update_listener_state", state)
    monkeypatch.setattr(messenger, "dispatch_incoming", dispatch)
    monkeypatch.setattr(
        messenger.ImapClient,
        "poll_inbox",
        lambda _self, *, after_uid, limit: MailPollBatch(
            uid_validity=9,
            latest_uid=42,
            messages=[_summary(41), _summary(42)],
        ),
    )

    async def stop_after_delay(_delay: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(messenger.asyncio, "sleep", stop_after_delay)

    with pytest.raises(asyncio.CancelledError):
        await adapter.listen()

    assert [call.args[0].id for call in dispatch.await_args_list] == ["9:41", "9:42"]
    assert [call.kwargs["cursor"] for call in state.await_args_list] == [
        messenger._encode_cursor(9, 41),  # pyright: ignore[reportPrivateUsage]
        messenger._encode_cursor(9, 42),  # pyright: ignore[reportPrivateUsage]
    ]
