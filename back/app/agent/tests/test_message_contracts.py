from __future__ import annotations

from uuid import uuid4

from app.agent.contracts import AIMessage, AIResult, TaskMessage


def test_text_fragments_merge_only_inside_the_same_semantic_stream() -> None:
    result = AIResult(prompt="Stream an answer")
    result.add_message(
        AIMessage(type="text", content="First ", stream_id="answer:1")
    )
    result.add_message(
        AIMessage(type="text", content="block", stream_id="answer:1")
    )
    result.add_message(
        AIMessage(type="text", content="Second block", stream_id="answer:2")
    )

    assert [message.content for message in result.messages] == [
        "First block",
        "Second block",
    ]


def test_terminal_text_reconciliation_separates_progress_from_final_answer() -> None:
    result = AIResult(prompt="Inspect the repository")
    result.add_message(AIMessage(type="text", content="I am inspecting."))
    result.add_message(
        AIMessage(type="tool", tool_name="file_read", content="README loaded")
    )
    result.add_message(AIMessage(type="text", content="Done."))

    result.reconcile_terminal_text("Done.")

    assert result.result == "Done."
    assert [
        (message.type, message.tool_name, message.content)
        for message in result.messages
    ] == [
        ("tool", "thinking", "I am inspecting."),
        ("tool", "file_read", "README loaded"),
        ("text", None, "Done."),
    ]


def test_terminal_text_reconciliation_splits_a_coalesced_final_suffix() -> None:
    result = AIResult(
        prompt="Inspect the repository",
        result="I am inspecting.Done.",
        messages=[AIMessage(type="text", content="I am inspecting.Done.")],
    )

    result.reconcile_terminal_text("Done.")

    assert result.result == "Done."
    assert [(message.type, message.content) for message in result.messages] == [
        ("tool", "I am inspecting."),
        ("text", "Done."),
    ]


def test_terminal_text_reconciliation_preserves_exact_terminal_whitespace() -> None:
    result = AIResult(prompt="Format the answer")
    result.add_message(AIMessage(type="text", content="Progress.\nFinal answer\n"))

    result.reconcile_terminal_text("Final answer\n")

    assert result.result == "Final answer\n"
    assert [(message.type, message.content) for message in result.messages] == [
        ("tool", "Progress."),
        ("text", "Final answer\n"),
    ]


def test_historical_provider_attachment_without_local_id_is_ignored() -> None:
    message = TaskMessage.model_validate(
        {
            "id": "provider-message-1",
            "room": {"local_id": str(uuid4()), "id": "provider-room-1"},
            "attachments": [
                {
                    "id": "provider-file-1",
                    "name": "archive.pdf",
                    "mime_type": "application/pdf",
                }
            ],
        }
    )

    assert message.file_ids == []
    assert message.attachments == []


def test_historical_provider_attachment_uses_parallel_local_file_id() -> None:
    room_id = uuid4()
    file_id = uuid4()

    message = TaskMessage.model_validate(
        {
            "external_message_id": "provider-message-1",
            "room_id": str(room_id),
            "room_external_id": "talk-token",
            "tool_code": "nextcloud",
            "file_ids": [str(file_id)],
            "attachments": [
                {
                    "id": "provider-file-1",
                    "uri": "https://provider.invalid/archive.pdf",
                    "name": "archive.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 123,
                }
            ],
        }
    )

    assert message.file_ids == [file_id]
    assert len(message.attachments) == 1
    attachment = message.attachments[0]
    assert attachment.id == file_id
    assert attachment.uri == f"nextcloud://talk-token/{file_id}"
    assert attachment.name == "archive.pdf"
    assert attachment.mime == "application/pdf"
    assert attachment.size == 123


def test_historical_local_id_replaces_provider_attachment_id() -> None:
    room_id = uuid4()
    file_id = uuid4()

    message = TaskMessage.model_validate(
        {
            "id": "provider-message-1",
            "tool_code": "nextcloud",
            "room": {"local_id": str(room_id), "id": "provider-room-1"},
            "attachments": [
                {
                    "id": "provider-file-1",
                    "local_id": str(file_id),
                    "name": "archive.pdf",
                }
            ],
        }
    )

    assert message.file_ids == [file_id]
    assert message.attachments[0].id == file_id
    assert message.attachments[0].uri == f"nextcloud://provider-room-1/{file_id}"
