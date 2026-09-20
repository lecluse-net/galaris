"""Manually verify that Pydantic AI receives message_history and forwards it to the LLM.

Usage from the backend container:
    docker compose exec backend python tests/manual/test_message_history.py

The script:
1. loads the LLM configured for the executor;
2. creates a Pydantic AI agent with that model;
3. builds a synthetic contextual message history;
4. sends a new prompt with that history;
5. checks that the LLM uses the prior context.
"""

import sys
from typing import Any, List

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import messages as _messages
from loguru import logger

sys.path.insert(0, "/app")

from app.harness.runtime import build_model_for_llm
from app.llm import llm_service, model_usages


async def create_pydantic_agent() -> tuple[PydanticAgent, Any]:
    """Load the executor LLM and create a Pydantic AI agent."""
    llm = await llm_service.get_profile_llm(model_usages.EXECUTOR)
    if llm is None:
        raise RuntimeError("No executor model is configured in the current profile.")
    model = await build_model_for_llm(llm)

    agent = PydanticAgent(
        model,
        system_prompt="You are a concise and direct assistant.",
    )

    logger.info(f"🤖 Agent created with {llm.llm_name}")
    return agent, llm


def build_test_history() -> List[_messages.ModelMessage]:
    """Build a synthetic conversation history to test context handling."""
    history: List[_messages.ModelMessage] = [
        # The user provides personal context.
        _messages.ModelRequest(
            parts=[_messages.UserPromptPart(content="My name is Jean and I live in Lyon.")],
        ),
        # The assistant replies.
        _messages.ModelResponse(
            parts=[_messages.TextPart(content="Nice to meet you, Jean! Lyon is a beautiful city.")],
        ),
        # The user asks another question without repeating their name.
        _messages.ModelRequest(
            parts=[_messages.UserPromptPart(content="What is the weather like where I live?")],
        ),
        # The assistant mentions Lyon.
        _messages.ModelResponse(
            parts=[_messages.TextPart(content="The weather in Lyon is often pleasant this season.")],
        ),
        # The user continues.
        _messages.ModelRequest(
            parts=[_messages.UserPromptPart(content="Thanks! What is my name?")],
        ),
        # The assistant mentions Jean.
        _messages.ModelResponse(
            parts=[_messages.TextPart(content="Your name is Jean.")],
        ),
    ]
    return history


async def test_with_history() -> None:
    """Send a prompt with a prebuilt message_history."""
    print("=" * 70)
    print("🔍 TEST: Pydantic AI with message_history")
    print("=" * 70)

    agent, llm = await create_pydantic_agent()
    history = build_test_history()

    print(f"\n📜 Built history: {len(history)} messages")
    for i, msg in enumerate(history):
        kind = "REQ" if msg.kind == "request" else "RES"
        for part in msg.parts:
            if hasattr(part, "content"):
                content = str(part.content)[:80]
                print(f"   [{i}] {kind}: {content}...")

    # This new prompt requires context from the history.
    new_prompt = "Which city do I live in?"

    print(f"\n📝 New prompt: '{new_prompt}'")
    print("   (The LLM should answer 'Lyon' based on the history.)")
    print("-" * 70)

    result = await agent.run(new_prompt, message_history=history)

    print("\n💬 LLM response:")
    print(f"   {result.output}")

    # Verify the response.
    if "lyon" in result.output.lower():
        print("\n✅ SUCCESS: the LLM used the conversation history!")
    else:
        print("\n❌ FAILURE: the LLM did not mention Lyon.")
        print("   The message_history may not have been forwarded correctly.")

    # Display complete messages for debugging.
    all_msgs = result.all_messages()
    print("\n📊 Statistics:")
    print(f"   - Total messages in the run: {len(all_msgs)}")
    print(f"   - New messages generated: {len(result.new_messages())}")
    print(f"   - Usage: {result.usage()}")

    print("\n" + "=" * 70)
    print("📋 ALL MESSAGES (debug)")
    print("=" * 70)
    for i, msg in enumerate(all_msgs):
        kind = msg.kind.upper()
        for part in msg.parts:
            pk = part.part_kind
            if hasattr(part, "content"):
                content = str(part.content)[:100]
                print(f"   [{i}] {kind}/{pk}: {content}...")
            else:
                print(f"   [{i}] {kind}/{pk}: (no content)")


async def test_without_history() -> None:
    """Control test: send the same prompt without history."""
    print("\n" + "=" * 70)
    print("🔍 CONTROL TEST: same prompt WITHOUT message_history")
    print("=" * 70)

    agent, llm = await create_pydantic_agent()
    new_prompt = "Which city do I live in?"

    print(f"\n📝 Prompt: '{new_prompt}'")
    print("   (Without history, the LLM cannot know that the answer is Lyon.)")
    print("-" * 70)

    result = await agent.run(new_prompt)

    print("\n💬 LLM response:")
    print(f"   {result.output}")

    if "lyon" in result.output.lower():
        print("\n⚠️ The LLM said Lyon without history (coincidence or context leak?).")
    else:
        print("\n✅ Expected behavior: the LLM does not know without history.")


async def main() -> None:
    await test_with_history()
    await test_without_history()
