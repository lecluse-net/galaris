"""Build prompts and contexts owned by the Hermes bridge."""

from __future__ import annotations

from core.params import Params, params_service
from app.agent.contracts import AgentRunRequest, AgentSnapshot
from app.agent import (
    ExecutorPromptContext,
    build_executor_prompt_tree,
    conversation_context_block,
    insert_before_suffix,
    render_prompt_tree,
    section,
)
from app.process import build_agent_process_advertisement
from app.tools.agent_registry import (
    build_agent_tool_advertisement,
    build_tool_context_values,
)

_HERMES_HISTORY_MAX_MESSAGES = 5

_HERMES_RUNTIME_GUIDE = """
# Galaris tools

You are connected to Galaris through MCP tools. The rights-filtered inventory below uses their
short server names; in your runtime tool list they carry the `mcp__galaris__` client prefix.
Always call the exact runtime name. Tool schemas provide the current signatures.

For every Galaris MCP file argument, use the exact canonical URI returned by file_schemes,
file_list, history, or another tool. Relative paths and runtime-local paths such as
`/opt/data/galaris/path` are not resource identifiers. Never convert a console://, Nextcloud,
Mail, HTTPS, or Messenger URI into one of them before calling an image, audio, file-share, or
Messenger tool.

Canonical conversation-history messages may start with `[timestamp | author]`; use that envelope
for chronology and speaker identity without echoing it. Current Task routing remains in the
Galaris message context, whose `language` controls user-facing text.
""".strip()

_HERMES_TURN_RULES = """
Turn semantics — critical:
- A reply without any tool call ENDS your run. Never announce that you are about to do something ("I'll search that", "on it!"): emit the tool call in the SAME reply. Plain text alone is reserved for your final answer, once the work is done.
- During a long run you may use an available messaging function for progress updates, then keep working in the same run.
- Tool calls from earlier turns belong to those turns: they never fulfill the current request. A correction ("send it to X instead, not Y") always requires a NEW tool call in this run. Never state that you performed an action unless its tool call succeeded in THIS run.
""".strip()


async def _has_galaris_skill(agent_id: int) -> bool:
    from app.skill import skill_service

    return "galaris" in await skill_service.get_assigned_codes(agent_id)


async def build_context_instructions(
    agent: AgentSnapshot,
    *,
    run_context_instructions: str = "",
) -> str:
    """Galaris instructions sent as an ephemeral system prompt for each request."""
    tool_advertisement = await build_agent_tool_advertisement(
        agent.id,
        runtime="hermes",
    )
    process_advertisement = await build_agent_process_advertisement(
        agent.id,
        tool_advertisement.tool_names,
    )
    runtime_rules: list[str] = []
    if await _has_galaris_skill(agent.id):
        runtime_rules.append(
            "Your assigned `galaris` skill is the detailed usage guide for the functions "
            "listed above. Read its relevant section before a non-trivial tool workflow. "
            "The rights-filtered inventory above remains authoritative."
        )
    runtime_rules.append(_HERMES_TURN_RULES)
    executor_rules = await params_service.get(Params.AI_EXECUTOR_SYSTEM_PROMPT)
    context = ExecutorPromptContext(
        agent_name=f"{agent.first_name} {agent.last_name}".strip() or agent.code,
        gender="female" if agent.gender == "F" else "male",
        job_title=agent.job_title or "agent",
        personality=agent.personality or "",
        job_description=agent.job_description or "",
        runtime_guide=_HERMES_RUNTIME_GUIDE,
        tool_advertisement=tool_advertisement.text,
        process_advertisement=process_advertisement,
        runtime_rules="\n\n".join(runtime_rules),
    )
    tree = build_executor_prompt_tree("task", context, suffix=executor_rules)
    if run_context_instructions.strip():
        tree = insert_before_suffix(
            tree,
            [
                section(
                    "run-context-instructions",
                    title="Run context instructions",
                    text=run_context_instructions,
                )
            ],
        )
    return render_prompt_tree(tree)


def hermes_context_values(task: AgentRunRequest) -> dict[str, str]:
    """Return Hermes values merged into the task prompt's JSON message context."""
    values = build_tool_context_values(task, runtime="hermes")
    if values is None:
        return {}
    return {
        "platform": str(values.get("platform") or ""),
        "room_id": str(values.get("room_id") or ""),
        "recent_attachments": str(values.get("recent_attachments") or ""),
        "recent_images": str(values.get("recent_images") or ""),
    }


def build_message_context(task: AgentRunRequest) -> str:
    """Build dynamic turn context containing a reminder of recent room messages."""
    history_block = conversation_context_block(
        task,
        max_messages=_HERMES_HISTORY_MAX_MESSAGES,
        include_current=False,
    )
    if not history_block:
        return ""
    return (
        "Recent messages in this room, for context — some may be missing from your "
        "own conversation history (posted by scheduled jobs or other agents). The "
        "current message is delivered separately.\n" + history_block
    )
