"""Manual Pydantic AI agent test for validating the installation and exploring the API.

Usage from the backend container:
    docker compose exec backend python tests/manual/test_pydantic_ai_simple.py

The script:
1. loads the LLM configured for the chatbot through existing parameters;
2. creates a Pydantic AI agent with OpenAIChatModel;
3. runs a basic conversation in blocking and streaming modes;
4. displays token and estimated-cost metrics.

It uses no LangChain dependency.
"""

import asyncio
import sys
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from loguru import logger
from devtools import debug

# Add /app to the import path.
sys.path.insert(0, "/app")

from app.llm import llm_provider_service, llm_service, model_usages
from app.harness.mcp_toolset import get_agent_mcp_servers
from app.tools.search_tool import search_web
from app.agent import agent_service


async def get_pydantic_ai_model() -> tuple[Any, OpenAIChatModel]:
    """Load the LLM configuration and create a Pydantic AI OpenAIChatModel."""

    # 1. Load the executor selected by the current profile.
    llm = await llm_service.get_profile_llm(model_usages.EXECUTOR)
    if llm is None:
        raise ValueError("No executor LLM is configured in the current profile.")

    if not llm.provider:
        raise ValueError(f"Provider not found for LLM '{llm.llm_name}'.")

    if not llm.provider.is_active:
        raise ValueError(f"Provider '{llm.provider.name}' is inactive.")

    # 2. Load the decrypted API key.
    provider_data = await llm_provider_service.get_provider_with_decrypted_key(
        llm.llm_provider_id
    )
    if provider_data is None:
        raise ValueError("Could not retrieve provider information.")

    provider, api_key = provider_data

    # 3. Let a bridge normalize its OpenAI-compatible endpoint when required.
    from app.llm.provider_facade import openai_protocol_base_url
    from app.llm.resource_discovery import provider_connection

    base_url = openai_protocol_base_url(
        provider_connection(provider, api_key)
    )

    # 4. Create an explicit Pydantic AI OpenAI provider without environment variables.
    openai_provider = OpenAIProvider(
        base_url=base_url,
        api_key=api_key or "sk-no-key-required",
    )

    # 5. Create the model with the current OpenAIChatModel class.
    model = OpenAIChatModel(llm.llm_name, provider=openai_provider)

    logger.info(
        f"🤖 Pydantic AI model initialized: {llm.llm_name} "
        f"(provider: {provider.name}, base_url: {base_url})"
    )

    return llm, model


def estimate_cost(llm: Any, usage: Any) -> float:
    """Estimate the cost in dollars from Pydantic AI input/output token usage."""
    cost = 0.0
    try:
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        if llm.cost_per_input_token is not None and llm.cost_per_output_token is not None:
            from app.llm.costing import token_cost

            cost = token_cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_rate=llm.cost_per_input_token,
                cached_input_rate=llm.cost_per_cached_input_token,
                output_rate=llm.cost_per_output_token,
            )
    except (AttributeError, TypeError):
        pass
    return cost


async def search_web_tool(query: str, max_results: int = 5) -> str:
    """
    Local tool that searches the web through SearXNG.

    The Pydantic AI agent decides whether to call it when a user question requires search.

    Args:
        query: Search terms.
        max_results: Maximum number of results. Defaults to 5.

    Returns:
        Formatted results or an error message.
    """
    debug(f"[TOOL CALL] search_web_tool(query='{query}', max_results={max_results})")
    try:
        # search_web uses synchronous httpx, so run it off the event loop.
        result = await asyncio.to_thread(search_web, query=query, max_results=max_results)
    except Exception as e:
        debug(f"[TOOL ERROR] {e}")
        return f"Search error: {e}"

    debug("[TOOL RESULT] Search complete")
    return result


async def test_run_simple(agent: Agent, llm: Any) -> None:
    """Test blocking mode, waiting for the complete response."""
    logger.info("\n📦 TEST 1: simple run (blocking mode)")
    logger.info("=" * 60)

    prompt = "What is the capital of France? Answer in one sentence."
    logger.info(f"👤 Prompt: {prompt}")

    result = await agent.run(prompt)

    # In Pydantic AI v1.x, output is an attribute and usage is a method.
    logger.info(f"🤖 Response: {result.output}")
    usage = result.usage()
    logger.info(f"📊 Usage: {usage}")
    logger.info(f"💰 Estimated cost: ${estimate_cost(llm, usage):.6f}")
    logger.info("=" * 60)


async def test_run_stream(agent: Agent, llm: Any) -> None:
    """Test streaming mode and display the response incrementally."""
    logger.info("\n📡 TEST 2: streaming run")
    logger.info("=" * 60)

    prompt = "Tell me a two-sentence joke about programmers."
    logger.info(f"👤 Prompt: {prompt}")
    logger.info("🤖 Streaming response: ", end="", flush=True)

    async with agent.run_stream(prompt) as result:
        async for text in result.stream_text(delta=True):
            print(text, end="", flush=True)
        print()  # Final newline.

    usage = result.usage()
    logger.info(f"\n📊 Usage: {usage}")
    logger.info(f"💰 Estimated cost: ${estimate_cost(llm, usage):.6f}")
    logger.info("=" * 60)


async def test_run_with_history(agent: Agent, llm: Any) -> None:
    """Test a multi-turn conversation with history."""
    logger.info("\n💬 TEST 3: multi-turn conversation")
    logger.info("=" * 60)

    # First turn.
    result = await agent.run("My first name is Nicolas.")
    logger.info("👤: My first name is Nicolas.")
    logger.info(f"🤖 : {result.output}")

    # The agent should remember the name on the second turn.
    result = await agent.run(
        "What is my first name?",
        message_history=result.all_messages(),
    )
    logger.info("👤: What is my first name?")
    logger.info(f"🤖 : {result.output}")
    logger.info(f"📊 Total usage: {result.usage()}")
    logger.info("=" * 60)


async def test_run_with_local_tools(agent: Agent, llm: Any, model: OpenAIChatModel) -> None:
    """Test a local web-search tool invoked by Pydantic AI."""
    from pydantic_ai import (
        AgentRunResultEvent,
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        PartStartEvent,
        PartDeltaEvent,
        PartEndEvent,
    )

    print("\n" + "=" * 60)
    print("🔧 TEST 4: agent with a local web-search tool")
    print("=" * 60)

    tool_agent = Agent(
        model,
        system_prompt=(
            "You are a friendly, concise, and slightly sarcastic AI assistant. "
            "You have access to search_web_tool for Internet searches through SearXNG. "
            "Use this tool whenever the user's question requires external information. "
            "Never invent data; call the search tool instead."
        ),
        tools=[search_web_tool],
    )

    prompt = "What are the latest Python news stories in 2025?"
    print(f"\n👤 Prompt: {prompt}")
    print("   The agent should decide to call search_web_tool.")

    print("\n📡 Real-time events:")
    print("-" * 40)

    full_response = ""
    final_usage = None
    async for event in tool_agent.run_stream_events(prompt):
        if isinstance(event, FunctionToolCallEvent):
            tool_name = getattr(event.part, "tool_name", "?")
            args = getattr(event.part, "args", {})
            print(f"   🛠️  TOOL CALL  : {tool_name} | args={args}")
        elif isinstance(event, FunctionToolResultEvent):
            tool_name = getattr(event.result, "tool_name", "?") if hasattr(event, "result") else "?"
            data = getattr(event.result, "data", "") if hasattr(event, "result") else str(event.content)
            print(f"   ✅ TOOL RESULT : {tool_name} | returned {len(str(data))} characters")
        elif isinstance(event, PartStartEvent):
            print(f"   ✨ PART START  : {type(event.part).__name__}")
        elif isinstance(event, PartDeltaEvent):
            delta_text = getattr(event.delta, "content_delta", "")
            if delta_text:
                print(delta_text, end="", flush=True)
                full_response += delta_text
        elif isinstance(event, PartEndEvent):
            print(f"\n   🏁 PART END    : {type(event.part).__name__}")
        elif isinstance(event, AgentRunResultEvent):
            print(f"\n   🎯 RUN END     : output={event.result.output[:100]}...")
            final_usage = event.result.usage()
        else:
            print(f"   📨 STREAM EVENT: {type(event).__name__}")

    print("\n" + "-" * 40)
    print("\n🤖 Complete final response:")
    debug(full_response)

    if final_usage is not None:
        print(f"\n💰 Estimated cost: ${estimate_cost(llm, final_usage):.6f}")
    else:
        print("\n💰 Estimated cost: N/A")
    print("=" * 60)


async def test_run_with_mcp_tools(model: OpenAIChatModel, llm: Any) -> None:
    """
    Test the native Pydantic AI MCP tools for agent 1.

    The function loads agent 1, lists its MCP connections, creates an authenticated Pydantic AI
    MCP server for each connection, starts an agent with those toolsets, and asks it to send a
    Nextcloud message to Nicolas.
    """
    from pydantic_ai import (
        AgentRunResultEvent,
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        PartStartEvent,
        PartDeltaEvent,
        PartEndEvent,
    )

    AGENT_ID = 1

    print("\n" + "=" * 60)
    print(f"🔧 TEST 5: agent with MCP tools for agent {AGENT_ID}")
    print("=" * 60)

    # 1. Load the agent.
    print(f"\n📋 Loading agent ID={AGENT_ID}...")
    agent = await agent_service.get(AGENT_ID)
    if not agent:
        print(f"❌ Agent {AGENT_ID} not found; aborting.")
        return
    print(f"✅ Agent found: {agent.first_name} {agent.last_name}")

    # 2. Load the native Pydantic AI MCP servers.
    print("\n🔧 Loading Pydantic AI MCP servers...")
    servers = await get_agent_mcp_servers(agent.id)
    print(f"✅ {len(servers)} MCP server(s) ready")

    if not servers:
        print("   ⚠️ No MCP connection is configured.")
        return

    if not servers:
        print("❌ No MCP server is available; aborting.")
        return

    # 4. Create the agent with MCP servers as toolsets.
    mcp_agent = Agent(
        model,
        system_prompt=(
            "You are a friendly, concise, and slightly sarcastic AI assistant. "
            "You have access to external tools through Model Context Protocol. "
            "Use them whenever necessary to fulfill the user's request. "
            "Never invent data; call the appropriate tool instead."
        ),
        toolsets=servers,
    )

    # 5. Ask the agent to send Nicolas a greeting through Nextcloud.
    prompt = (
        "Use the nextcloud_talk_send_message tool to send Nicolas a greeting through Nextcloud."
    )
    print(f"\n👤 Prompt: {prompt}")
    print("   The agent should decide to call nextcloud_talk_send_message.")

    print("\n📡 Real-time events:")
    print("-" * 40)

    full_response = ""
    final_usage = None
    async for event in mcp_agent.run_stream_events(prompt):
        if isinstance(event, FunctionToolCallEvent):
            tool_name = getattr(event.part, "tool_name", "?")
            args = getattr(event.part, "args", {})
            print(f"   🛠️  TOOL CALL  : {tool_name} | args={args}")
        elif isinstance(event, FunctionToolResultEvent):
            tool_name = getattr(event.result, "tool_name", "?") if hasattr(event, "result") else "?"
            data = getattr(event.result, "data", "") if hasattr(event, "result") else str(event.content)
            print(f"   ✅ TOOL RESULT : {tool_name} | returned {len(str(data))} characters")
        elif isinstance(event, PartStartEvent):
            print(f"   ✨ PART START  : {type(event.part).__name__}")
        elif isinstance(event, PartDeltaEvent):
            delta_text = getattr(event.delta, "content_delta", "")
            if delta_text:
                print(delta_text, end="", flush=True)
                full_response += delta_text
        elif isinstance(event, PartEndEvent):
            print(f"\n   🏁 PART END    : {type(event.part).__name__}")
        elif isinstance(event, AgentRunResultEvent):
            print(f"\n   🎯 RUN END     : output={event.result.output[:100]}...")
            final_usage = event.result.usage()
        else:
            print(f"   📨 STREAM EVENT: {type(event).__name__}")

    print("\n" + "-" * 40)
    print("\n🤖 Complete final response:")
    debug(full_response)

    if final_usage is not None:
        print(f"\n💰 Estimated cost: ${estimate_cost(llm, final_usage):.6f}")
    else:
        print("\n💰 Estimated cost: N/A")
    print("=" * 60)


async def main() -> None:
    logger.info("🚀 Starting the simple Pydantic AI agent test")
    logger.info("   This is 100% Pydantic AI, with no LangChain.")

    # 1. Load the configured model.
    llm, model = await get_pydantic_ai_model()

    # 2. Create the agent.
    agent = Agent(
        model,
        system_prompt=(
            "You are a friendly, concise, and slightly sarcastic AI assistant."
        ),
    )

    # 3. Run the tests.
    #await test_run_simple(agent, llm)
    #await test_run_stream(agent, llm)
    #await test_run_with_history(agent, llm)
    #await test_run_with_local_tools(agent, llm, model)
    await test_run_with_mcp_tools(model, llm)

    logger.info("\n✅ All Pydantic AI tests are complete!")
    logger.info("   You can now experiment by changing the prompts in this file.")
