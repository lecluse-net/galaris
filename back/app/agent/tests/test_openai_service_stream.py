# pyright: reportPrivateUsage=false

import json
from types import SimpleNamespace, TracebackType
from typing import Any, AsyncIterator, cast
from uuid import UUID, uuid4

import pytest

from app.agent.models import Agent
from app.agent import openai_service as service
from app.agent.contracts import AIMessage, ExecutionResult
from app.agent.openai_schemas import ChatCompletionRequest, Message
from app.task.models import TaskStatus
from app.task.schemas import TaskCreate


@pytest.mark.asyncio
async def test_openai_stream_relays_only_text_task_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> bool:
            return False

    execution_result = ExecutionResult(
        prompt="",
        messages=[
            AIMessage(type="tool", tool_name="thinking", content="hidden"),
            AIMessage(type="text", content="ok"),
        ],
        result="ok",
    )

    async def fake_get_by_id(task_id: UUID) -> SimpleNamespace:
        return SimpleNamespace(
            id=task_id,
            status=TaskStatus.SUCCESS,
            get_execution_result=lambda: execution_result,
        )

    monkeypatch.setattr("core.database.database.get_db_session", lambda: FakeSession())
    monkeypatch.setattr("app.task.task_service.get_by_id", fake_get_by_id)

    stream = service._local_stream_response(
        task_id=UUID("00000000-0000-0000-0000-000000000001"),
        model="demo",
        conversation_id="conv-1",
    )

    lines = [line async for line in stream]
    payloads: list[dict[str, Any]] = [
        json.loads(line.removeprefix("data: "))
        for line in lines
        if line.startswith("data: ") and line.strip() != "data: [DONE]"
    ]

    assert all("choices" in payload or "error" in payload for payload in payloads)
    assert all(payload["choices"][0]["delta"] != {"content": "hidden"} for payload in payloads)
    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert payloads[0]["conversation_id"] == "conv-1"
    assert payloads[1]["choices"][0]["delta"] == {"content": "ok"}


@pytest.mark.asyncio
async def test_prepare_openai_task_is_scheduler_managed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_task = SimpleNamespace(id=uuid4())

    async def fake_create(task_data: TaskCreate) -> SimpleNamespace:
        assert task_data.message_platform == "openai"
        assert task_data.data == {"conversation_id": "conv-1"}
        return created_task

    async def fake_get_by_id(task_id: UUID) -> None:
        return None

    monkeypatch.setattr("app.task.task_service.create", fake_create)
    monkeypatch.setattr("app.task.task_service.get_by_id", fake_get_by_id)

    agent = cast(Agent, SimpleNamespace(id=12, code="demo"))
    request = ChatCompletionRequest(
        model="demo",
        messages=[Message(role="user", content="Hello")],
    )

    task = await service.prepare_task(agent, request, "conv-1")

    assert task is created_task


@pytest.mark.asyncio
async def test_shared_agent_api_session_is_isolated_between_humans(monkeypatch):
    from core.user import user_service

    drafts = []
    async def create(draft):
        drafts.append(draft)
        return SimpleNamespace(id=uuid4())

    async def load(_task_id):
        return None

    monkeypatch.setattr("app.task.task_service.create", create)
    monkeypatch.setattr("app.task.task_service.get_by_id", load)
    agent = cast(Agent, SimpleNamespace(id=12, code="shared"))
    request = ChatCompletionRequest(model="shared", messages=[Message(role="user", content="Hello")])
    previous = user_service.get_current_user_id()
    try:
        for human_id in (7, 8):
            user_service.set_current_user(SimpleNamespace(id=human_id))
            await service.prepare_task(agent, request, "same-client-conversation")
        assert drafts[0].data["conversation_id"] != drafts[1].data["conversation_id"]
        assert drafts[0].agent_id == drafts[1].agent_id == 12
    finally:
        user_service.set_current_user(SimpleNamespace(id=previous) if previous is not None else None)


@pytest.mark.asyncio
async def test_openai_stream_wakes_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    task_id = uuid4()
    task = SimpleNamespace(id=task_id)
    calls: list[tuple[UUID, bool]] = []

    async def fake_prepare_task(
        agent: Agent,
        request: ChatCompletionRequest,
        conversation_id: str | None,
    ) -> SimpleNamespace:
        return task

    def fake_go_next(woken_task_id: UUID, fast: bool = False) -> None:
        calls.append((woken_task_id, fast))

    async def fake_stream() -> AsyncIterator[str]:
        yield "data: [DONE]\n\n"

    def fake_local_stream_response(
        task_id: UUID,
        model: str,
        conversation_id: str,
    ) -> AsyncIterator[str]:
        return fake_stream()

    monkeypatch.setattr(service, "prepare_task", fake_prepare_task)
    monkeypatch.setattr("app.task.runner.go_next", fake_go_next)
    monkeypatch.setattr(service, "_local_stream_response", fake_local_stream_response)

    agent = cast(Agent, SimpleNamespace(id=12, code="demo"))
    request = ChatCompletionRequest(
        model="demo",
        messages=[Message(role="user", content="Hello")],
        stream=True,
    )

    result = await service.run_local_chat_completion(agent, request, {"conversation_id": "conv-1"})

    assert hasattr(result, "__aiter__")
    assert calls == [(task_id, True)]
