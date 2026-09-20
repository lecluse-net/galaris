from app.messenger.interactions import (
    ChoiceOption,
    ChoiceRequest,
    _option_from_answer,
    _render_choice_text,
)


def test_numbered_answer_selects_matching_choice() -> None:
    options = [
        ChoiceOption(id="once", label="Approve once"),
        ChoiceOption(id="session", label="Approve for this session"),
        ChoiceOption(id="deny", label="Deny"),
    ]

    assert _option_from_answer(options, "1").id == "once"
    assert _option_from_answer(options, " 2. ").id == "session"
    assert _option_from_answer(options, "3)").id == "deny"


def test_alias_answer_selects_matching_choice() -> None:
    options = [
        ChoiceOption(id="once", label="Approve once", aliases=["yes", "ok"]),
        ChoiceOption(id="deny", label="Deny", aliases=["no"]),
    ]

    assert _option_from_answer(options, "OK").id == "once"
    assert _option_from_answer(options, "no").id == "deny"
    assert _option_from_answer(options, "maybe") is None


def test_unambiguous_alias_can_prefix_a_natural_answer() -> None:
    options = [
        ChoiceOption(
            id="once",
            label="Autoriser une fois",
            aliases=["j’autorise", "oui"],
        ),
        ChoiceOption(id="deny", label="Refuser", aliases=["non"]),
    ]

    assert (
        _option_from_answer(options, "J’autorise la génération du PDF").id
        == "once"
    )
    assert _option_from_answer(options, "non conforme") is None


def test_choice_text_is_numbered() -> None:
    text = _render_choice_text(
        ChoiceRequest(
            kind="test",
            title="Approval required",
            body="Dangerous command",
            options=[
                ChoiceOption(id="once", label="Approve once"),
                ChoiceOption(id="deny", label="Deny"),
            ],
            language="en",
        )
    )

    assert "Reply with the corresponding number" in text
    assert "1. Approve once" in text
    assert "2. Deny" in text


# ──────────────────────────────────────────────────────────────────────────
# Free-text answers.
# ──────────────────────────────────────────────────────────────────────────

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from app.messenger.interactions import (
    ChoiceResolution,
    PendingChoice,
    _reset_for_tests,
    create_choice,
    list_pending_choices,
    register_choice_handler,
    resolve_pending_choice,
    resolve_from_message,
)
from app.messenger._observations import (
    ObservedMessengerMessage as Message,
)
from app.messenger.models import (
    Interaction,
    Message as MessageModel,
    Room,
    MessengerUser,
)


class _FakeMessenger:
    connection_id = 0
    tool_id = 42

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_to_room(self, room_id: str, text: str, reply_to: str | None = None) -> Message:
        self.sent.append((room_id, text))
        return Message(id="prompt-1", text=text)


def _incoming(
    text: str, room_id: str = "room-1", user_id: str = "alice"
) -> MessageModel:
    message = MessageModel(
        id=uuid4(),
        connection_id=cast(int, None),
        tool_id=42,
        platform="test",
        remote_message_id="answer-1",
        direction="inbound",
        text=text,
    )
    message.room = cast(Room, SimpleNamespace(id=room_id))
    message.sender = cast(
        MessengerUser,
        SimpleNamespace(id=user_id, external_id=user_id),
    )
    return message


def test_choice_text_free_text_with_options_mentions_both() -> None:
    text = _render_choice_text(
        ChoiceRequest(
            kind="test",
            title="Question",
            options=[ChoiceOption(id="a", label="Choice A")],
            free_text=True,
            language="en",
        )
    )

    assert "or with free text" in text
    assert "1. Choice A" in text


def test_choice_text_pure_free_text_has_no_numbering() -> None:
    text = _render_choice_text(
        ChoiceRequest(
            kind="test",
            title="Open question",
            body="Details?",
            free_text=True,
            language="en",
        )
    )

    assert "number" not in text
    assert "Open question" in text
    assert "Details?" in text


@pytest.mark.asyncio
async def test_create_choice_requires_options_unless_free_text() -> None:
    with pytest.raises(ValueError):
        await create_choice(
            _FakeMessenger(),  # type: ignore[arg-type]
            agent_id=7,
            room_id="room-1",
            request=ChoiceRequest(kind="test", title="Without options"),
        )


@pytest.mark.asyncio
async def test_create_choice_idempotency_key_prevents_duplicate_prompt(db) -> None:
    await _reset_for_tests()
    messenger = _FakeMessenger()
    request = ChoiceRequest(kind="free-test", title="Question?", free_text=True)

    first = await create_choice(
        messenger,  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=request,
        idempotency_key="same-effect",
    )
    second = await create_choice(
        messenger,  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=request,
        idempotency_key="same-effect",
    )

    assert second.id == first.id
    assert len(messenger.sent) == 1
    await _reset_for_tests()


@pytest.mark.asyncio
async def test_room_choice_scoped_to_user_rejects_another_sender(db) -> None:
    await _reset_for_tests()
    await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        user_id="alice",
        request=ChoiceRequest(
            kind="closed-test",
            title="Private approval",
            options=[ChoiceOption(id="yes", label="Yes")],
        ),
    )

    assert (
        await resolve_from_message(
            _incoming("1", user_id="mallory"), agent_id=7
        )
        is None
    )
    assert await resolve_from_message(_incoming("1"), agent_id=7) is not None
    await _reset_for_tests()


@pytest.mark.asyncio
async def test_free_text_answer_resolves_and_reaches_handler(db) -> None:
    await _reset_for_tests()
    received: list[tuple[PendingChoice, ChoiceResolution]] = []

    async def _handler(choice: PendingChoice, resolution: ChoiceResolution) -> None:
        received.append((choice, resolution))

    register_choice_handler("free-test", _handler)
    await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=ChoiceRequest(kind="free-test", title="Question?", free_text=True),
    )

    resolution = await resolve_from_message(_incoming("My free-text answer"), agent_id=7)

    assert resolution is not None
    assert resolution.option_id is None
    assert resolution.text == "My free-text answer"
    assert received and received[0][1].text == "My free-text answer"
    # The interaction is consumed, so the next message returns to the dispatcher.
    assert await resolve_from_message(_incoming("another message"), agent_id=7) is None
    await _reset_for_tests()


@pytest.mark.asyncio
async def test_free_text_option_match_takes_precedence(db) -> None:
    await _reset_for_tests()
    await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=ChoiceRequest(
            kind="free-test",
            title="Question?",
            options=[ChoiceOption(id="yes", label="Yes")],
            free_text=True,
        ),
    )

    resolution = await resolve_from_message(_incoming("1"), agent_id=7)

    assert resolution is not None
    assert resolution.option_id == "yes"
    await _reset_for_tests()


@pytest.mark.asyncio
async def test_closed_choice_ignores_non_matching_text(db) -> None:
    await _reset_for_tests()
    received: list[ChoiceResolution] = []

    async def handler(choice: PendingChoice, resolution: ChoiceResolution) -> None:
        received.append(resolution)

    register_choice_handler("closed-test", handler)
    pending = await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=ChoiceRequest(
            kind="closed-test",
            title="Approval?",
            options=[ChoiceOption(id="yes", label="Yes")],
        ),
    )
    try:
        assert await resolve_from_message(_incoming("maybe later"), agent_id=7) is None
        record = await db.get(Interaction, pending.id)
        assert record is not None
        await db.refresh(record)
        assert record.status == "PENDING"
        assert record.resolution is None
        assert record.resolved_at is None
        assert received == []

        # Ignoring the unrelated text must not consume the following valid answer.
        resolution = await resolve_from_message(_incoming("1"), agent_id=7)
        assert resolution is not None and resolution.option_id == "yes"
        assert received == [resolution]
    finally:
        await _reset_for_tests()


@pytest.mark.asyncio
async def test_conversation_controller_can_resolve_a_scoped_closed_choice(db) -> None:
    await _reset_for_tests()
    received: list[ChoiceResolution] = []

    async def handler(choice: PendingChoice, resolution: ChoiceResolution) -> None:
        _ = choice
        received.append(resolution)

    register_choice_handler("closed-test", handler)
    pending = await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        user_id="alice",
        request=ChoiceRequest(
            kind="closed-test",
            title="Approval?",
            options=[
                ChoiceOption(id="once", label="Approve once"),
                ChoiceOption(id="deny", label="Deny"),
            ],
        ),
    )

    choices = await list_pending_choices(
        agent_id=7,
        connection_id=None,
        tool_id=42,
        room_id="room-1",
        user_id="alice",
    )
    assert [choice.id for choice in choices] == [pending.id]
    assert not await list_pending_choices(
        agent_id=7,
        connection_id=None,
        tool_id=42,
        room_id="room-1",
        user_id="mallory",
    )

    resolution, delivered = await resolve_pending_choice(
        reference=f"#{pending.reference.lower()}",
        option_id="deny",
        response_text="Ne fais surtout pas ça.",
        agent_id=7,
        connection_id=None,
        tool_id=42,
        room_id="room-1",
        user_id="alice",
    )

    assert delivered is True
    assert resolution.option_id == "deny"
    assert resolution.text == "Ne fais surtout pas ça."
    assert received == [resolution]

    replay, replay_delivered = await resolve_pending_choice(
        reference=pending.reference,
        option_id="deny",
        response_text="Ne fais surtout pas ça.",
        agent_id=7,
        connection_id=None,
        tool_id=42,
        room_id="room-1",
        user_id="alice",
    )
    assert replay == resolution
    assert replay_delivered is True
    assert received == [resolution]

    with pytest.raises(ValueError, match="another option"):
        await resolve_pending_choice(
            reference=pending.reference,
            option_id="once",
            response_text="Actually approve it.",
            agent_id=7,
            connection_id=None,
            tool_id=42,
            room_id="room-1",
            user_id="alice",
        )
    await _reset_for_tests()
    await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=ChoiceRequest(
            kind="closed-test",
            title="Question?",
            options=[ChoiceOption(id="yes", label="Yes")],
        ),
    )

    # Text outside the options of a closed interaction is not consumed.
    assert await resolve_from_message(_incoming("free answer"), agent_id=7) is None
    await _reset_for_tests()


@pytest.mark.asyncio
async def test_ambiguous_room_answer_requires_reference(db) -> None:
    await _reset_for_tests()
    received: list[str] = []

    async def handler(choice: PendingChoice, resolution: ChoiceResolution) -> None:
        _ = resolution
        received.append(choice.reference)

    register_choice_handler("ambiguous", handler)
    first = await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=ChoiceRequest(kind="ambiguous", title="First", free_text=True),
    )
    await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=ChoiceRequest(kind="ambiguous", title="Second", free_text=True),
    )

    assert await resolve_from_message(_incoming("answer"), agent_id=7) is None
    resolution = await resolve_from_message(
        _incoming(f"answer #{first.reference}"), agent_id=7
    )

    assert resolution is not None
    assert resolution.text == "answer"
    assert received == [first.reference]
    await _reset_for_tests()


@pytest.mark.asyncio
async def test_failed_handler_is_replayed_from_persistent_resolution(db) -> None:
    from app.messenger import interactions

    await _reset_for_tests()
    calls = 0

    async def flaky_handler(choice: PendingChoice, resolution: ChoiceResolution) -> None:
        nonlocal calls
        _ = (choice, resolution)
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")

    register_choice_handler("retry-handler", flaky_handler)
    pending = await create_choice(
        _FakeMessenger(),  # type: ignore[arg-type]
        agent_id=7,
        room_id="room-1",
        request=ChoiceRequest(kind="retry-handler", title="Retry", free_text=True),
    )
    assert await resolve_from_message(_incoming("ok"), agent_id=7) is not None

    record = await db.get(Interaction, pending.id)
    assert record is not None and record.status == "PROCESSING"
    record.processing_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()

    await interactions.retry_pending_interactions()

    await db.refresh(record)
    assert calls == 2
    assert record.status == "RESOLVED"
    await _reset_for_tests()
