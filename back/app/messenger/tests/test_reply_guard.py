from uuid import uuid4

from app.messenger import reply_guard


def test_reply_guard_is_scoped_by_task_in_same_room() -> None:
    room_id = "shared-room"
    first_task = uuid4()
    second_task = uuid4()

    reply_guard.clear_room(7, room_id, task_id=first_task)
    reply_guard.clear_room(7, room_id, task_id=second_task)
    reply_guard.note_reply(7, room_id, "first reply", task_id=first_task)

    assert reply_guard.replied_recently(7, room_id, task_id=first_task) is True
    assert reply_guard.replied_recently(7, room_id, task_id=second_task) is False
    assert (
        reply_guard.text_already_sent(
            7, room_id, "first reply", task_id=second_task
        )
        is False
    )


def test_clearing_retry_scope_does_not_clear_concurrent_task() -> None:
    room_id = "shared-room-retry"
    first_task = uuid4()
    second_task = uuid4()
    reply_guard.note_reply(7, room_id, "A", task_id=first_task)
    reply_guard.note_reply(7, room_id, "B", task_id=second_task)

    reply_guard.clear_room(7, room_id, task_id=first_task)

    assert reply_guard.replied_recently(7, room_id, task_id=first_task) is False
    assert reply_guard.replied_recently(7, room_id, task_id=second_task) is True


def test_same_room_id_on_two_connections_has_independent_delivery_state() -> None:
    task_id = uuid4()
    room_id = "42"
    reply_guard.clear_room(7, room_id, task_id=task_id, connection_id=10)
    reply_guard.clear_room(7, room_id, task_id=task_id, connection_id=11)
    reply_guard.note_reply(
        7,
        room_id,
        "Telegram reply",
        task_id=task_id,
        connection_id=10,
    )

    assert reply_guard.replied_recently(
        7, room_id, task_id=task_id, connection_id=10
    )
    assert not reply_guard.replied_recently(
        7, room_id, task_id=task_id, connection_id=11
    )
