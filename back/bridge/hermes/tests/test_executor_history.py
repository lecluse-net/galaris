from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from app.agent.contracts import AgentRunRequest
from bridge.hermes import executor


def test_canonical_conversation_snapshot_replaces_runtime_cache() -> None:
    request = cast(
        AgentRunRequest,
        SimpleNamespace(
            conversation_history=(
                {"id": "m1", "role": "user", "text": "canonical question"},
                {
                    "id": "m2",
                    "role": "assistant",
                    "text": "canonical answer",
                    "sender": {"agent_id": 7},
                },
            )
        ),
    )
    runtime_cache = [
        {"role": "user", "content": "stale deleted question"},
        {"role": "assistant", "content": "stale deleted answer"},
    ]

    history = executor._merged_conversation_history(request, runtime_cache)

    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert "<galaris_message_context>" not in history[0]["content"]
    assert "<conversation_history_metadata>" not in history[0]["content"]
    assert history[0]["content"] == "canonical question"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "canonical answer"


def test_runtime_session_is_used_only_without_a_common_snapshot() -> None:
    request = cast(
        AgentRunRequest,
        SimpleNamespace(conversation_history=()),
    )
    runtime_cache = [{"role": "user", "content": "direct Hermes session"}]

    assert executor._merged_conversation_history(request, runtime_cache) == runtime_cache


def test_canonical_history_keeps_file_only_message() -> None:
    file_id = uuid4()
    request = cast(
        AgentRunRequest,
        SimpleNamespace(
            conversation_history=(
                {
                    "id": "file-only",
                    "role": "user",
                    "text": "",
                    "attachments": [
                        {
                            "name": "rapport.pdf",
                            "uri": f"matrix-primary://!room:test/{file_id}",
                        }
                    ],
                },
            )
        ),
    )

    history = executor._merged_conversation_history(request, [])
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert "<galaris_message_context>" not in history[0]["content"]
    assert history[0]["content"].endswith(
        f"[file: rapport.pdf] matrix-primary://!room:test/{file_id}"
    )


def test_canonical_history_keeps_attachment_post_date_and_sender() -> None:
    posted_at = 1_700_000_000
    expected_timestamp = datetime.fromtimestamp(
        posted_at, tz=timezone.utc
    ).astimezone().isoformat(timespec="minutes")
    file_id = uuid4()
    request = cast(
        AgentRunRequest,
        SimpleNamespace(
            conversation_history=(
                {
                    "id": "dated-file",
                    "role": "user",
                    "timestamp": posted_at,
                    "sender": {"id": "nicolas", "display_name": "Nicolas"},
                    "attachments": [
                        {
                            "name": "rapport.pdf",
                            "uri": f"nextcloud://talk-room/{file_id}",
                        }
                    ],
                },
            )
        ),
    )

    history = executor._merged_conversation_history(request, [])
    assert history[0]["content"].startswith(
        f"[{expected_timestamp} | Nicolas] "
    )
    assert "<galaris_message_context>" not in history[0]["content"]
    assert "<conversation_history_metadata>" not in history[0]["content"]
    assert history[0]["content"].endswith(
        f"[file: rapport.pdf] nextcloud://talk-room/{file_id}"
    )
