"""System prompt owned by the internal Pydantic AI harness."""

from __future__ import annotations

from app.agent.contracts import AgentSnapshot

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.prompt_tree import PromptNode, PromptTree


_SKILLS_GUIDE = """
Specialized instructions are available as deferred capabilities. Review their descriptions and,
when one matches the current request, call `load_capability` before acting. Follow the loaded
skill instructions for the rest of the run. Do not load unrelated skills.
""".strip()


async def build_harness_system_prompt(
    agent: AgentSnapshot,
    *,
    has_skills: bool = False,
    galaris_tools: str = "",
    run_context_instructions: str = "",
) -> str:
    """Build the internal harness system prompt from shared sections."""
    from app.agent import executor_service

    from app.agent.prompt_tree import render_prompt_tree

    return render_prompt_tree(
        harness_system_prompt_tree(
            await executor_service.build_system_prompt_tree(agent),
            has_skills=has_skills,
            galaris_tools=galaris_tools,
            run_context_instructions=run_context_instructions,
        )
    )


def harness_system_prompt_tree(
    common_tree: "PromptTree",
    *,
    has_skills: bool = False,
    galaris_tools: str = "",
    run_context_instructions: str = "",
) -> "PromptTree":
    """Insert internal-harness nodes before the Task executor's final suffix."""

    from app.agent.prompt_tree import insert_before_suffix, section

    nodes: list["PromptNode"] = []
    if galaris_tools.strip():
        nodes.append(
            section(
                "galaris-tools",
                title="Galaris tools",
                text=galaris_tools,
            )
        )
    if has_skills:
        nodes.append(section("skills", title="Skills", text=_SKILLS_GUIDE))
    if run_context_instructions.strip():
        nodes.append(
            section(
                "run-context-instructions",
                title="Run context instructions",
                text=run_context_instructions,
            )
        )
    return insert_before_suffix(common_tree, nodes)


def harness_system_prompt_sections(
    common_tree: "PromptTree",
    *,
    has_skills: bool = False,
    galaris_tools: str = "",
    run_context_instructions: str = "",
) -> "PromptTree":
    """Compatibility alias for the JSON-tree implementation."""

    return harness_system_prompt_tree(
        common_tree,
        has_skills=has_skills,
        galaris_tools=galaris_tools,
        run_context_instructions=run_context_instructions,
    )
