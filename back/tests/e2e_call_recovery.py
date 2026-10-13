"""Synthetic provider boundary for a real internal-harness recovery journey."""
import asyncio

from pydantic_ai.messages import UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage


states = {}


class RecoveryModel(FunctionModel):
    async def count_tokens(self, _messages, _settings, _parameters):
        return RequestUsage(input_tokens=1)


def register(agent_id):
    states[agent_id] = {"calls": 0, "closed": False, "guided": False}


async def build_model(_llm, *, agent_id, **_kwargs):
    state = states[agent_id]

    async def generate(messages, _info):
        state["calls"] += 1
        if state["calls"] == 1:
            try:
                yield "Synthetic generation is active."
                await asyncio.Future()
            finally:
                state["closed"] = True
        else:
            assert state["closed"], "The interrupted provider must close before recovery"
            state["guided"] = any(
                isinstance(part, UserPromptPart) and "DEMANDE UTILISATEUR" in str(part.content)
                for message in messages for part in message.parts
            )
            assert state["guided"], "Recovery must instruct the model to change approach"
            yield "Synthetic guided recovery completed."

    return RecoveryModel(stream_function=generate)
