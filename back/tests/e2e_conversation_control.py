"""Synthetic model boundary; the conversation controller and scheduler stay real."""

import asyncio

from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

states = {}


class ControlledModel(FunctionModel):
    async def count_tokens(self, _messages, _settings, _parameters):
        return RequestUsage(input_tokens=1)


def register(agent_id):
    states[agent_id] = {"calls": 0, "closed": 0, "reply_now": False, "gate": asyncio.Event()}


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
            await state["gate"].wait()
            yield " terminée."
        finally:
            state["closed"] += 1

    return ControlledModel(stream_function=generate)
