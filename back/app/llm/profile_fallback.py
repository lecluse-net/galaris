"""Bounded provider failover for one model request; never replay the tool loop."""

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Generator
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, cast
from types import TracebackType

import httpx
import httpx2
from openai import APIError
from pydantic import BaseModel
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ModelResponseStreamEvent
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage
from .provider_facade import ProviderAuthenticationError, ProviderUnavailableError


class ProfileFallbackRoute(BaseModel):
    profile_id: int
    from_llm_id: int | None = None
    reason: str | None = None


profile_fallback_route: ContextVar[ProfileFallbackRoute | None] = ContextVar(
    "profile_fallback_route", default=None,
)


@contextmanager
def fallback_route_scope(route: ProfileFallbackRoute | None) -> Generator[None]:
    token = profile_fallback_route.set(route)
    try:
        yield
    finally:
        profile_fallback_route.reset(token)


def provider_failure_allows_fallback(exc: Exception) -> bool:
    """Only provider availability/access failures, never local authorization or budgets."""
    if isinstance(exc, ExceptionGroup):
        group = cast(ExceptionGroup[Exception], exc)
        return all(provider_failure_allows_fallback(item) for item in group.exceptions)
    if isinstance(exc, (httpx.TransportError, httpx2.TransportError)):
        return True
    if isinstance(exc, (ProviderAuthenticationError, ProviderUnavailableError)):
        return True
    if isinstance(exc, (PermissionError, ValueError)):
        return False
    if isinstance(exc, ModelHTTPError):
        return exc.status_code in {401, 403, 404, 408, 429, 500, 502, 503, 504, 529}
    if isinstance(exc, APIError):
        status = getattr(exc, "status_code", None)
        if status is not None:
            return status in {401, 403, 404, 408, 429, 500, 502, 503, 504, 529}
    if isinstance(exc.__cause__, Exception) and provider_failure_allows_fallback(exc.__cause__):
        return True
    # Some SSE adapters/SDKs discard the HTTP code. Keep this boundary narrow.
    message = str(exc).lower()
    return any(marker in message for marker in (
        "servers are currently overloaded", "overloaded_error", "provider_overloaded",
    ))


class _FallbackStream(StreamedResponse):
    """Forward live events; only the successful provider response enters history."""

    def __init__(
        self, current: StreamedResponse,
        open_secondary: Callable[[Exception], Awaitable[StreamedResponse]],
    ) -> None:
        super().__init__(model_request_parameters=current.model_request_parameters)
        self.current = current
        self.open_secondary = open_secondary

    def __aiter__(self) -> AsyncIterator[ModelResponseStreamEvent]:
        if self._event_iterator is None:
            self._event_iterator = self._get_event_iterator()
        return self._event_iterator

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        try:
            async for event in self.current:
                self.final_result_event = self.current.final_result_event
                yield event
        except Exception as exc:
            if not provider_failure_allows_fallback(exc):
                raise
            self.current = await self.open_secondary(exc)
            self.final_result_event = None
            async for event in self.current:
                self.final_result_event = self.current.final_result_event
                yield event

    def get(self) -> ModelResponse:
        return self.current.get()

    @property
    def usage(self) -> RequestUsage:
        return self.current.usage

    async def close_stream(self) -> None:
        await self.current.cancel()

    @property
    def model_name(self) -> str:
        return self.current.model_name

    @property
    def provider_name(self) -> str | None:
        return self.current.provider_name

    @property
    def provider_url(self) -> str | None:
        return self.current.provider_url

    @property
    def timestamp(self) -> datetime:
        return self.current.timestamp


class ProfileFallbackModel(WrapperModel):
    """Freeze two models, then keep the secondary for the rest of this run."""

    def __init__(self, primary: Model, secondary: Model, *, profile_id: int, primary_llm_id: int) -> None:
        super().__init__(primary)
        self.secondary = secondary
        self.route = ProfileFallbackRoute(profile_id=profile_id)
        self.primary_llm_id = primary_llm_id
        self.using_secondary = False

    async def __aenter__(self) -> "ProfileFallbackModel":
        await self.wrapped.__aenter__()
        try:
            await self.secondary.__aenter__()
        except BaseException:
            await self.wrapped.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        try:
            await self.secondary.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            await self.wrapped.__aexit__(exc_type, exc_val, exc_tb)
        return None

    def prepare_request(
        self, model_settings: ModelSettings | None, model_request_parameters: ModelRequestParameters,
    ) -> tuple[ModelSettings | None, ModelRequestParameters]:
        # Each candidate prepares its own provider profile after selection.
        return model_settings, model_request_parameters

    def prepare_messages(
        self, messages: list[ModelMessage], model_request_parameters: ModelRequestParameters | None = None,
    ) -> list[ModelMessage]:
        return messages

    def _switch(self, exc: Exception) -> None:
        self.using_secondary = True
        self.route = self.route.model_copy(update={
            "from_llm_id": self.primary_llm_id,
            "reason": f"{type(exc).__name__}: {exc}"[:2000],
        })

    async def _record_failed_call(self, exc: Exception, response: ModelResponse | None = None) -> None:
        from .call_capture import text_call_capture
        from .text_inference import persist_events, message_for_part
        from app.agent.contracts import AIResult

        capture = text_call_capture.get()
        if capture is None or capture.call_id is None:
            return
        # Protocol workers already own their physical terminal result. This path
        # is for the composed RecordedTextModel, whose outer request continues.
        if capture.request.get("schema_version") == "galaris.protocol-inference-request/v1":
            return
        result = AIResult(prompt=str(capture.request.get("prompt", "")), success=False, metadata={
            "llm_call_id": str(capture.call_id), "error": str(exc),
        })
        if response is not None:
            for index, part in enumerate(response.parts):
                message = message_for_part(capture.call_id, index, part)
                if message is not None:
                    message.success = False
                    result.add_message(message)
        events = await persist_events(capture.call_id, [{"kind": "result", "result": result.model_dump(mode="json")}])
        capture.results.append(events[0]["result"])
        await capture.publish(events[0])

    def _selected_settings(self, settings: ModelSettings | None) -> ModelSettings | None:
        if not self.using_secondary or settings is None:
            return settings
        return cast(ModelSettings, {key: value for key, value in settings.items() if key not in {
            "openai_reasoning_effort", "openai_store", "openai_reasoning_context",
            "openai_send_reasoning_ids", "openai_reasoning_summary", "openai_previous_response_id",
        }})

    async def request(
        self, messages: list[ModelMessage], model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        failure: Exception | None = None
        with fallback_route_scope(self.route):
            try:
                selected = self.secondary if self.using_secondary else self.wrapped
                return await selected.request(messages, self._selected_settings(model_settings), model_request_parameters)
            except Exception as exc:
                if self.using_secondary or not provider_failure_allows_fallback(exc):
                    raise
                failure = exc
        assert failure is not None
        await self._record_failed_call(failure)
        self._switch(failure)
        with fallback_route_scope(self.route):
            return await self.secondary.request(messages, self._selected_settings(model_settings), model_request_parameters)

    @asynccontextmanager
    async def request_stream(
        self, messages: list[ModelMessage], model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters, run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        async with AsyncExitStack() as primary_stack, AsyncExitStack() as secondary_stack:
            async def open_model(model: Model, stack: AsyncExitStack) -> StreamedResponse:
                stack.enter_context(fallback_route_scope(self.route))
                return await stack.enter_async_context(model.request_stream(
                    messages, self._selected_settings(model_settings), model_request_parameters, run_context,
                ))

            async def open_secondary(exc: Exception) -> StreamedResponse:
                await primary_stack.aclose()
                await self._record_failed_call(exc, stream.get() if stream is not None else None)
                self._switch(exc)
                return await open_model(self.secondary, secondary_stack)

            if self.using_secondary:
                yield await open_model(self.secondary, secondary_stack)
                return
            stream: StreamedResponse | None = None
            try:
                stream = await open_model(self.wrapped, primary_stack)
            except Exception as exc:
                if not provider_failure_allows_fallback(exc):
                    raise
                yield await open_secondary(exc)
                return
            yield _FallbackStream(stream, open_secondary)
