"""Live smoke test for proxy streaming and terminal-tool short-circuiting."""

import asyncio

import httpx
from sqlalchemy import delete, select

from app.agent.models import Agent
from app.llm import llm_service
from app.llm.models import LLMCall
from app.mcp.models import AgentMcpToken
from core.database import get_db_session, load_models
from core.util.encryption import decrypt_value


GATEWAY = "http://127.0.0.1:8000/api/llm/openai/chat/completions"


async def main() -> None:
    load_models()
    async with get_db_session() as db:
        agent = await db.get(Agent, 1)
        if agent is None:
            raise RuntimeError("Smoke-test agent not found")
        llm = await llm_service.get_llm_for_agent(agent)
        if llm is None:
            raise RuntimeError("Smoke-test LLM not found")
        token_record = (await db.execute(
            select(AgentMcpToken).where(
                AgentMcpToken.agent_id == agent.id,
                AgentMcpToken.hidden.is_(True),
                AgentMcpToken.enabled.is_(True),
            )
        )).scalar_one()
        token = decrypt_value(token_record.token_encrypted)
        model = llm.code

    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK only."}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    async with httpx.AsyncClient(timeout=90) as client:
        async with client.stream("POST", GATEWAY, headers=headers, json=body) as response:
            response.raise_for_status()
            call_id = response.headers.get("X-Galaris-LLM-Call-Id")
            if not call_id:
                raise RuntimeError("Identifiant llm_call absent")
            async for _line in response.aiter_lines():
                pass

        terminal_body = {
            "model": model,
            "messages": [
                {"role": "user", "content": "Say hello"},
                {"role": "assistant", "tool_calls": [{
                    "id": "call-smoke",
                    "type": "function",
                    "function": {
                        "name": "mcp__galaris__messenger_room_send_message",
                        "arguments": '{"message":"Hello"}',
                    },
                }]},
                {"role": "tool", "tool_call_id": "call-smoke", "content": "Message sent"},
            ],
            "stream": True,
        }
        async with client.stream("POST", GATEWAY, headers=headers, json=terminal_body) as response:
            response.raise_for_status()
            if response.headers.get("X-Galaris-LLM-Call-Id"):
                raise RuntimeError("The terminal turn created a second LLM call")
            async for _line in response.aiter_lines():
                pass

    await asyncio.sleep(0.5)
    async with get_db_session() as db:
        call = await db.get(LLMCall, call_id)
        if call is None or call.status != "completed" or call.completed_at is None:
            raise RuntimeError(f"Finalisation incorrecte: {getattr(call, 'status', None)}")
        print(f"OK call={call.id} status={call.status} response={call.response_text!r}")
        await db.execute(delete(LLMCall).where(LLMCall.id == call.id))


if __name__ == "__main__":
    asyncio.run(main())
