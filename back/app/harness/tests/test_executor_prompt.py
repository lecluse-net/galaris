from types import SimpleNamespace
from typing import cast

from app.agent import executor_service
from app.harness.prompt import harness_system_prompt_sections
from app.agent.models import Agent


def _agent() -> Agent:
    return cast(
        Agent,
        SimpleNamespace(
            first_name="Ada",
            last_name="Lovelace",
            title=SimpleNamespace(gender="F"),
            job_title="Analyst",
            personality="Rigorous",
            job_description="Handle Galaris requests.",
        ),
    )


def test_common_system_prompt_does_not_include_runtime_specific_tools() -> None:
    prompt = executor_service.render_prompt_sections(
        executor_service.common_system_prompt_sections(_agent(), None)
    )

    assert "# Galaris tools" not in prompt
    assert "tools_list()" not in prompt
    assert "# Your identity" in prompt
    assert "**Your name:** **Ada Lovelace**" in prompt
    assert "# Your personality\n\nRigorous" in prompt
    assert "authorship or signature preferences" in prompt


def test_harness_system_prompt_sections_route_deferred_skills() -> None:
    prompt = executor_service.render_prompt_sections(
        harness_system_prompt_sections(
            executor_service.common_system_prompt_sections(_agent(), None),
            has_skills=True,
        )
    )

    assert "# Skills" in prompt
    assert "load_capability" in prompt
    assert "Do not load unrelated skills" in prompt
    assert "# Galaris tools" not in prompt


def test_harness_system_prompt_omits_skill_routing_without_capabilities() -> None:
    prompt = executor_service.render_prompt_sections(
        harness_system_prompt_sections(
            executor_service.common_system_prompt_sections(_agent(), None)
        )
    )

    assert "# Skills" not in prompt
    assert "load_capability" not in prompt


def test_harness_system_prompt_includes_only_supplied_rights_filtered_inventory() -> None:
    prompt = executor_service.render_prompt_sections(
        harness_system_prompt_sections(
            executor_service.common_system_prompt_sections(_agent(), None),
            galaris_tools=(
                "Only the following functions are available:\n"
                "- `galaris`: `process_list`, `process_get`, `process_start`"
            ),
        )
    )

    assert "# Galaris tools" in prompt
    assert "`process_start`" in prompt
    assert "image_generate" not in prompt
    assert prompt.index("# Galaris tools") < prompt.index("`process_start`")


def test_task_executor_suffix_remains_last_after_run_context() -> None:
    prompt = executor_service.render_prompt_sections(
        harness_system_prompt_sections(
            executor_service.common_system_prompt_sections(
                _agent(), "FINAL EXECUTOR SUFFIX"
            ),
            run_context_instructions="Current run constraint.",
        )
    )

    assert "# Run context instructions" in prompt
    assert prompt.index("Current run constraint.") < prompt.index("FINAL EXECUTOR SUFFIX")
    assert prompt.endswith("FINAL EXECUTOR SUFFIX")
