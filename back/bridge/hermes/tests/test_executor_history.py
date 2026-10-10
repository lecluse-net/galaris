from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.agent.contracts import AgentRunCheckpoint, AgentRunRequest, ExecutionResult
from bridge.hermes import executor


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting", [True, False])
async def test_missing_resumed_run_closes_authorization_wait_without_replaying_effects(
    db, monkeypatch: pytest.MonkeyPatch, waiting: bool,
) -> None:
    from app.agent import executor_service
    from .test_kanban_executor import _request

    request_ids = [uuid4()] if waiting else []
    prior = ExecutionResult(
        prompt="Synthetic Hermes recovery",
        success=False,
        result="Prior progress",
        schema_version="galaris.execution-result/v2",
        disposition="waiting_for_authorization" if waiting else "completed",
        authorization_requests=request_ids,
        tools_used=["synthetic_write"],
        cost=0.25,
    )
    checkpoint = AgentRunCheckpoint(
        driver_code="hermes", runtime_run_id="synthetic-missing-run",
        status="waiting_for_authorization" if waiting else "running", result=prior,
        data={"session_id": "synthetic-session", "execution_strategy": "direct"},
    )
    request = replace(
        _request(effort="standard", execution_strategy="direct", checkpoint=checkpoint),
        task_data={"language": "en"},
    )
    requests = []

    def respond(http_request):
        requests.append((http_request.method, http_request.url.path))
        return httpx.Response(404 if http_request.method == "GET" else 200, json={})

    monkeypatch.setattr(
        executor.client.httpx, "AsyncClient",
        partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setattr("app.messenger.resolve_task_messaging", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(executor_service, "build_task_prompt", AsyncMock(return_value=prior.prompt))
    monkeypatch.setattr(executor, "build_context_instructions", AsyncMock(return_value="Synthetic context"))
    monkeypatch.setattr(executor, "current_content", AsyncMock(return_value=prior.prompt))
    monkeypatch.setattr(
        executor.session_binding, "get_or_create_session_id",
        AsyncMock(return_value="synthetic-session"),
    )

    events = [event async for event in executor._stream(request)]
    result = events[-1].result
    assert result is not None and not result.success
    assert result.disposition == "completed" and result.authorization_requests == []
    assert result.failure is not None and result.failure.code == "effect_unknown"
    assert result.failure.retry == "never" and result.failure.effects == "possible"
    assert result.cost == prior.cost and result.tools_used == prior.tools_used
    assert prior.authorization_requests == request_ids
    assert prior.disposition == ("waiting_for_authorization" if waiting else "completed")
    assert ExecutionResult.model_validate(result.model_dump(mode="json")) == result
    assert ("GET", "/v1/runs/synthetic-missing-run") in requests
    assert not any(method == "POST" and "/runs" in path for method, path in requests)


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
