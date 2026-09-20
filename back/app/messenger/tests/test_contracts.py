from uuid import uuid4

from app.messenger import resolve_effective_topic_id


def test_explicit_message_topic_has_priority_over_room_topic() -> None:
    message_topic_id = uuid4()

    assert resolve_effective_topic_id(
        message_topic_id,
        topic_overridden=True,
        room_topic_id=uuid4(),
    ) == message_topic_id


def test_room_topic_is_the_default_for_an_unoverridden_message() -> None:
    room_topic_id = uuid4()

    assert resolve_effective_topic_id(
        uuid4(),
        topic_overridden=False,
        room_topic_id=room_topic_id,
    ) == room_topic_id


def test_historical_message_topic_is_preserved_without_a_room_default() -> None:
    historical_topic_id = uuid4()

    assert resolve_effective_topic_id(
        historical_topic_id,
        topic_overridden=False,
        room_topic_id=None,
    ) == historical_topic_id


def test_missing_message_and_room_topics_stays_missing() -> None:
    assert (
        resolve_effective_topic_id(
            None,
            topic_overridden=False,
            room_topic_id=None,
        )
        is None
    )
