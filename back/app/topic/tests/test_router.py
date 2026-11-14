from app.topic import router


def test_topic_mutations_require_edit_privilege() -> None:
    for endpoint in (
        router.create_topic,
        router.update_topic,
        router.merge_topic,
        router.split_topic,
        router.delete_topic,
        router.read_topic_memories,
        router.change_resource_topic,
        router.move_library_document,
    ):
        metadata = getattr(endpoint, "_authorize_meta")
        assert metadata["privileges"] == ["TOPIC_EDIT"]


def test_topic_content_requires_topic_access() -> None:
    metadata = getattr(router.read_topic_content, "_authorize_meta")
    assert metadata["privileges"] == ["TOPIC_ACCESS", "TOPIC_EDIT"]


def test_topic_refs_are_available_to_execution_monitoring() -> None:
    metadata = getattr(router.read_topic_refs, "_authorize_meta")
    assert set(metadata["privileges"]) == {
        "TASK_ACCESS", "TASK_EDIT", "TOPIC_ACCESS", "TOPIC_EDIT",
        "CONVERSATION_ACCESS", "CONVERSATION_CONTROL", "VOICE_HISTORY_ACCESS", "VOICE_HISTORY_CONTROL",
        "CHAT_ACCESS", "DOCUMENT_ACCESS", "DOCUMENT_EDIT", "DOCUMENT_ADMIN",
        "MEMORY_ACCESS", "MEMORY_EDIT", "MEMORY_ADMIN", "DATASET_READ", "DATASET_EDIT", "DATASET_ADMIN",
    }
