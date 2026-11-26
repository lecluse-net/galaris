"""Synthetic model boundary; the conversation controller and scheduler stay real."""

import asyncio
from contextlib import asynccontextmanager, nullcontext
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.usage import RequestUsage

from app.llm.pydantic_ai_utils import InternalLLMChatModel

states = {}
embedded_provider = APIRouter()
embedded_models: dict[str, asyncio.Event] = {}


class _EmbeddedFixtureModelGate:
    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None):
        # Only the registered synthetic model can make its real loopback request.
        permit = override_allow_model_requests(True) if self.model_name in embedded_models else nullcontext()
        with permit:
            async with super().request_stream(messages, model_settings, model_request_parameters, run_context) as stream:
                yield stream


class EmbeddedFixtureChatModel(_EmbeddedFixtureModelGate, OpenAIChatModel):
    pass


class EmbeddedFixtureInternalChatModel(_EmbeddedFixtureModelGate, InternalLLMChatModel):
    pass


@embedded_provider.post("/api/__test/embedded-model/v1/chat/completions")
async def complete_embedded(request: Request) -> StreamingResponse:
    body = await request.json()
    model = body.get("model")
    gate = embedded_models.get(model)
    if gate is None or not body.get("stream"):
        raise HTTPException(400, "Unknown embedded conversation fixture")
    request_id = f"chatcmpl-browser-{uuid4().hex}"

    async def stream():
        for content in ("Réponse progressive", " terminée.", None):
            if content == " terminée.":
                await asyncio.wait_for(gate.wait(), timeout=45)
            chunk = {
                "id": request_id, "object": "chat.completion.chunk", "created": 1, "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": content} if content else {},
                             "finish_reason": None if content else "stop"}],
            }
            if content is None:
                chunk["usage"] = {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"x-request-id": request_id})


class ControlledModel(FunctionModel):
    async def count_tokens(self, _messages, _settings, _parameters):
        return RequestUsage(input_tokens=1)


def load_topic_model(purpose):
    answers = {"dream.topic_continuity": {"same_topic_probability": 1.0},
               "dream.topic_creation": {"title": "Synthetic load topic"},
               "dream.topic_reuse": {"topic_id": None, "confidence": 1.0}}
    if purpose in answers:
        return ControlledModel(function=lambda *_: ModelResponse(parts=[TextPart(json.dumps(answers[purpose]))]))
    return None


def register(agent_id, *, response_delay=None):
    states[agent_id] = {"calls": 0, "closed": 0, "reply_now": False, "gate": asyncio.Event(),
                        "response_delay": response_delay}


async def build_model(_llm, *, agent_id, purpose=None, **_kwargs):
    state = states[agent_id]
    if str(purpose) == "agent.dispatch":
        return ControlledModel(function=lambda _messages, _info: ModelResponse(parts=[
            TextPart('{"route":"EXEC","effort":"standard","language":"fr"}')
        ]))

    async def generate(messages, info):
        state["calls"] += 1
        reply_now = any(isinstance(part, UserPromptPart) and "The user clicked Reply now" in str(part.content)
                        for message in messages for part in message.parts)
        if reply_now:
            assert not info.function_tools, "Reply now must expose no tools, including tool search"
            state["reply_now"] = True
            yield "Réponse immédiate avec les éléments disponibles."
            return
        try:
            yield "Réponse progressive"
            if state["response_delay"] is None:
                await state["gate"].wait()
            else:
                await asyncio.sleep(state["response_delay"])
            yield " terminée."
        finally:
            state["closed"] += 1

    return ControlledModel(stream_function=generate)
