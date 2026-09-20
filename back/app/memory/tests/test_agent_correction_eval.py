"""Provider-free end-to-end evaluations of the durable correction policy."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.memory.context import memory_policy_instructions


@pytest.mark.asyncio
async def test_agent_writes_correction_before_forgetting_obsolete_memory() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    model_step = 0

    def respond(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_step
        model_step += 1
        if model_step == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "memory_remember",
                        {
                            "title": "Préférence corrigée",
                            "content": "Nicolas préfère les réponses concises.",
                        },
                        "remember-correction",
                    )
                ]
            )
        if model_step == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "memory_forget",
                        {"memory_id": "11111111-1111-1111-1111-111111111111"},
                        "forget-obsolete",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Correction enregistrée.")])

    agent: Agent[None, str] = Agent(
        FunctionModel(respond),
        instructions=memory_policy_instructions(),
    )

    @agent.tool_plain(name="memory_remember")
    async def remember(title: str, content: str) -> str:
        calls.append(("remember", {"title": title, "content": content}))
        return '{"memory_id":"22222222-2222-2222-2222-222222222222"}'

    @agent.tool_plain(name="memory_forget")
    async def forget(memory_id: str) -> str:
        calls.append(("forget", {"memory_id": memory_id}))
        return '{"forgotten":true}'

    result = await agent.run(
        "La préférence précédente est fausse. "
        "Je préfère maintenant des réponses concises."
    )

    assert result.output == "Correction enregistrée."
    assert [name for name, _payload in calls] == ["remember", "forget"]


@pytest.mark.asyncio
async def test_agent_does_not_forget_an_ambiguous_search_result() -> None:
    calls: list[str] = []
    model_step = 0

    def respond(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> ModelResponse:
        nonlocal model_step
        model_step += 1
        if model_step == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "memory_search",
                        {"query": "ancienne préférence de format"},
                        "search-obsolete",
                    )
                ]
            )
        return ModelResponse(
            parts=[
                TextPart(
                    "Deux souvenirs correspondent ; une précision est nécessaire."
                )
            ]
        )

    agent: Agent[None, str] = Agent(
        FunctionModel(respond),
        instructions=memory_policy_instructions(),
    )

    @agent.tool_plain(name="memory_search")
    async def search(query: str) -> str:
        calls.append(f"search:{query}")
        return (
            '{"hits":['
            '{"id":"11111111-1111-1111-1111-111111111111"},'
            '{"id":"22222222-2222-2222-2222-222222222222"}'
            "]}"
        )

    @agent.tool_plain(name="memory_forget")
    async def forget(memory_id: str) -> str:
        calls.append(f"forget:{memory_id}")
        return '{"forgotten":true}'

    result = await agent.run(
        "Oublie mon ancienne préférence de format."
    )

    assert "précision" in result.output
    assert calls == ["search:ancienne préférence de format"]
