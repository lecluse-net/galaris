"""Record native SDK model responses without changing the agent's execution loop."""

import asyncio
import json
import time
import anyio
from importlib.metadata import version
from typing import Any, cast
from uuid import UUID

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    PartStartEvent,
    PartDeltaEvent,
    PartEndEvent,
    TextPart,
    ThinkingPart,
    ToolCallPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from app.agent.contracts import AIMessage, AIResult
from core.database import get_db_session
from .call_capture import TextCallCapture
from .inference_journal import append_events


class _CommittedCancellation(asyncio.CancelledError):
    def __init__(self, events: list[dict[str, Any]]) -> None:
        super().__init__("Inference cancelled after its journal write")
        self.events = events


async def persist_events(call_id: UUID, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    async def writer() -> list[dict[str, Any]]:
        # A short-lived execution writer owns its session, never the Lab transaction.
        async with get_db_session():
            return await append_events(call_id, payloads)

    task = asyncio.create_task(writer())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Pydantic AI's AnyIO scope can cancel every subsequent await. Waiting
        # unshielded here would propagate that second cancellation to the writer.
        with anyio.CancelScope(shield=True):
            await asyncio.shield(task)
        raise _CommittedCancellation(task.result()) from None


def message_for_part(call_id: UUID, index: int, part: object) -> AIMessage | None:
    if not isinstance(part, (TextPart, ThinkingPart, ToolCallPart)):
        return None
    content = ""
    arguments: dict[str, Any] | None = None
    if isinstance(part, ToolCallPart):
        content = part.args if isinstance(part.args, str) else (
            json.dumps(part.args, ensure_ascii=False) if part.args is not None else ""
        )
        try:
            decoded = json.loads(content)
            if isinstance(decoded, dict):
                arguments = cast(dict[str, Any], decoded)
        except ValueError:
            pass
    else:
        content = part.content
    return AIMessage(
        type="text" if isinstance(part, TextPart) else "tool",
        tool_name=(part.tool_name if isinstance(part, ToolCallPart)
                   else "thinking" if isinstance(part, ThinkingPart) else None),
        tool_arguments=arguments,
        tool_call_external_id=part.tool_call_id if isinstance(part, ToolCallPart) else None,
        content=content,
        stream_id=f"{call_id}:{index}",
        stream_mode="snapshot",
    )


class RecordedTextModel(WrapperModel):
    """Consume the SDK stream and return its unchanged native response."""

    def __init__(self, wrapped: Model, capture: TextCallCapture) -> None:
        super().__init__(wrapped)
        self.capture = capture

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        capture = self.capture
        capture.call_id = None
        model_settings = cast(
            ModelSettings,
            {
                **(model_settings or {}),
                **capture.request.get("parameters", {}),
            },
        )
        capture.request = {
            **capture.request,
            "sdk_messages": ModelMessagesTypeAdapter.dump_python(messages, mode="json"),
            "model_settings": dict(model_settings or {}),
            "pydantic_ai_version": version("pydantic-ai-slim"),
        }
        result = AIResult(
            prompt=str(capture.request["prompt"]),
            system_prompt=str(capture.request["system_prompt"]),
        )
        pending: dict[int, AIMessage] = {}
        committed_content: dict[int, str] = {}
        committed_messages: dict[int, AIMessage] = {}
        last_flush = 0.0
        started = time.monotonic()

        async def flush() -> None:
            nonlocal last_flush, result
            if not pending or capture.call_id is None:
                return
            updates: list[AIMessage] = []
            for index, message in pending.items():
                previous = committed_content.get(index, "")
                if message == committed_messages.get(index):
                    continue
                update = message.model_copy(deep=True)
                if message.tool_call_external_id is None and message.content.startswith(previous):
                    update.content = message.content[len(previous) :]
                    update.stream_mode = "delta"
                updates.append(update)
            payloads = [
                {"kind": "message", "message": message.model_dump(mode="json")}
                for message in updates
            ]
            if not payloads:
                pending.clear()
                return
            projected = result.model_copy(deep=True)
            for message in updates:
                projected.add_message(message.model_copy(deep=True))
            cancellation: _CommittedCancellation | None = None
            try:
                events = await persist_events(capture.call_id, payloads)
            except _CommittedCancellation as exc:
                events = exc.events
                cancellation = exc
            result = projected
            committed_content.update({index: message.content for index, message in pending.items()})
            committed_messages.update({index: message.model_copy(deep=True)
                                       for index, message in pending.items()})
            pending.clear()
            last_flush = time.monotonic()
            if cancellation is not None:
                raise cancellation
            for event in events:
                await capture.publish(event)

        response: ModelResponse | None = None
        failure: BaseException | None = None
        try:
            async with self.wrapped.request_stream(
                messages,
                model_settings,
                model_request_parameters,
            ) as stream:
                async for event in stream:
                    if not isinstance(event, (PartStartEvent, PartDeltaEvent, PartEndEvent)):
                        continue
                    if capture.call_id is None:
                        raise RuntimeError("The model stream was not bound to a persisted LLMCall.")
                    parts = stream.get().parts
                    if event.index >= len(parts):
                        continue
                    part = parts[event.index]
                    if not isinstance(part, (TextPart, ThinkingPart, ToolCallPart)):
                        continue
                    message = message_for_part(capture.call_id, event.index, part)
                    if message is None:
                        continue
                    pending[event.index] = message
                    if (
                        isinstance(event, (PartStartEvent, PartEndEvent))
                        or time.monotonic() - last_flush >= 0.1
                        or sum(
                            max(0, len(message.content) - len(committed_content.get(index, "")))
                            for index, message in pending.items()
                        )
                        >= 4096
                    ):
                        await flush()
                response = stream.get()
            await flush()
            if response.state != "complete":
                raise RuntimeError("The provider stream ended without a complete response.")
        except BaseException as exc:
            failure = exc
            result.success = False
            result.metadata["error"] = str(exc) or type(exc).__name__
        finally:

            async def finish() -> None:
                if capture.call_id is None:
                    return
                await flush()
                result.execution_time = time.monotonic() - started
                result.metadata["llm_call_id"] = str(capture.call_id)
                payload: dict[str, Any] = {
                    "kind": "result",
                    "result": result.model_dump(mode="json"),
                }
                if response is not None:
                    payload["sdk_response"] = ModelMessagesTypeAdapter.dump_python(
                        [response], mode="json"
                    )
                events = await persist_events(capture.call_id, [payload])
                capture.results.append(events[0]["result"])
                await capture.publish(events[0])

            # As with gateway cleanup, preserve partial messages when the caller is cancelled.
            finish_task = asyncio.create_task(finish())
            try:
                await asyncio.shield(finish_task)
            except asyncio.CancelledError:
                with anyio.CancelScope(shield=True):
                    await asyncio.shield(finish_task)
                raise
        if failure is not None:
            raise failure
        assert response is not None
        return response
