"""Manual test for a basic chatbot using agent 1's MCP tools."""

from loguru import logger

from app.harness.runtime import create_agent
from app.harness.mcp_toolset import get_agent_mcp_servers
from app.agent import agent_service
from app.llm import llm_service, model_usages


# ID of the agent to test.
agent_id = 1


async def main():
    # 1. Load the LLM configured for the executor.
    llm = await llm_service.get_profile_llm(model_usages.EXECUTOR)
    if llm is None:
        raise RuntimeError("No executor model is configured in the current profile.")

    # 2. Load the agent.
    agent = await agent_service.get(agent_id)
    if not agent:
        logger.error(f"❌ Agent {agent_id} not found")
        return

    # 3. Load the agent's MCP tools.
    logger.info("\n🔧 Loading MCP servers for the agent...")
    all_mcp_servers = await get_agent_mcp_servers(agent.id)
    logger.info(f"✅ Loaded {len(all_mcp_servers)} MCP server(s)")

    if not all_mcp_servers:
        logger.error("❌ No MCP server is available; stopping the test")
        return

    # 4. Create the agent with the LLM and all MCP tools.
    agent = await create_agent(
        llm=llm,
        mcp_servers=all_mcp_servers,
    )

    # 5. Prepare the prompt.
    prompt = "Can you list the agents in my company?"

    # 6. Run the agent.
    logger.info("\n🚀 Running the agent...")
    logger.info("=" * 60)

    async for message in agent.run(prompt):
        if message.type == "text":
            print(message.content, end="", flush=True)
        elif message.type == "tool":
            logger.info(f"\n🔧 Tool: {message.tool_name} → {message.content}")

    print()  # Final newline.

    # 7. Complete the test.
    logger.info("\n" + "=" * 60)
    logger.success("✅ Test complete!")

    # MCP clients are closed by the garbage collector or managed by the execution context.
