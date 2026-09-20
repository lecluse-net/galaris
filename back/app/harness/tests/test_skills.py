from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.harness import runtime
from app.harness.skills import (
    _MAX_INLINE_SKILL_INSTRUCTIONS_CHARS,
    _build_capability,
    _capability_instructions,
    _read_skill_resource,
    _section_schema_values,
    build_internal_skill_capabilities,
)
from app.skill import skill_service, storage
from app.skill import learning_service


def _write_skill(root: Path, code: str) -> None:
    directory = root / code
    (directory / "references").mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {code}\ndescription: Research workflow.\n---\n\n"
        "Read references/guide.md when needed.\n",
        encoding="utf-8",
    )
    (directory / "references/guide.md").write_text("Use primary sources.\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_assigned_skills_become_deferred_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "research")
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))

    async def assigned_codes(agent_id: int) -> list[str]:
        assert agent_id == 42
        return ["research"]

    async def learned_skills(_agent_id: int) -> list[Any]:
        return []

    monkeypatch.setattr(skill_service, "get_assigned_codes", assigned_codes)
    monkeypatch.setattr(learning_service, "list_injectable", learned_skills)

    capabilities = await build_internal_skill_capabilities(42)

    assert len(capabilities) == 1
    capability = cast(Any, capabilities[0])
    assert capability.id == "research"
    assert capability.description == "Research workflow."
    assert capability.defer_loading is True
    assert set(capability.get_toolset().tools) == {"skill_research_read_file"}
    read_tool = cast(Any, capability.get_toolset().tools["skill_research_read_file"])
    assert "Exact available resource paths: SKILL.md, references/guide.md" in (
        read_tool.description
    )
    assert "without translating or paraphrasing" in read_tool.description
    assert "references/guide.md" in _read_skill_resource("research")
    assert _read_skill_resource("research", "references/guide.md") == "Use primary sources.\n"
    missing = _read_skill_resource("research", "../secret")
    assert "Unable to read resource" in missing
    assert "Available files: SKILL.md, references/guide.md" in missing
    assert "Do not retry the same missing path" in missing

    visible_tools: set[str] = set()

    def respond(
        _messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        visible_tools.update(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart(content="No capability needed.")])

    model = FunctionModel(respond)
    await PydanticAgent(model, capabilities=capabilities).run("Research this topic")
    assert "load_capability" in visible_tools
    assert "skill_research_read_file" not in visible_tools


@pytest.mark.asyncio
async def test_injectable_learned_skills_become_additional_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def assigned_codes(_agent_id: int) -> list[str]:
        return []

    async def learned_skills(_agent_id: int) -> list[Any]:
        return [
            SimpleNamespace(
                code="learned-agent-verify",
                description="Verify a deployment after changing it.",
                markdown=(
                    "---\nname: learned-agent-verify\n"
                    "description: Verify a deployment after changing it.\n---\n\n"
                    "Run the health check.\n"
                ),
            )
        ]

    monkeypatch.setattr(skill_service, "get_assigned_codes", assigned_codes)
    monkeypatch.setattr(learning_service, "list_injectable", learned_skills)

    capabilities = await build_internal_skill_capabilities(42)

    assert len(capabilities) == 1
    capability = cast(Any, capabilities[0])
    assert capability.id == "learned-agent-verify"
    assert capability.defer_loading is True
    instructions = cast(list[str], capability.get_instructions())
    assert "Run the health check" in instructions[0]


def test_large_skill_capability_uses_progressive_section_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    directory = root / "large-guide"
    directory.mkdir(parents=True)
    guide = (
        "---\nname: large-guide\ndescription: Large guide.\n---\n\n"
        "# Large guide\n\nIntro.\n\n"
        "## Audio transcription\n\nUse audio_transcribe.\n\n"
        "### Safety\n\nNever read the original multimedia file.\n\n"
        "## Console\n\n" + ("Verbose console documentation.\n" * 600)
    )
    (directory / "SKILL.md").write_text(guide, encoding="utf-8")
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))

    compact = _capability_instructions("large-guide", guide, "skill_large_guide_read_file")

    assert len(guide) > _MAX_INLINE_SKILL_INSTRUCTIONS_CHARS
    assert len(compact) < 2_000
    assert "Audio transcription" in compact
    assert "intentionally kept out" in compact
    assert 'path="SKILL.md"' in compact
    assert "never guess" in compact
    assert "never translate or paraphrase" in compact
    audio = _read_skill_resource("large-guide", "SKILL.md", "## Audio transcription")
    assert "Use audio_transcribe" in audio
    assert "Never read the original multimedia file" in audio
    assert "Verbose console documentation" not in audio
    assert _section_schema_values("large-guide") == (
        "Large guide",
        "Audio transcription",
        "Safety",
        "Console",
    )


@pytest.mark.asyncio
async def test_skill_reader_can_recover_after_two_invalid_resource_guesses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    directory = root / "research"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: research\ndescription: Research workflow.\n---\n\n"
        "## Persistent console: shell, Python, and Git\n\nUse the console.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))
    capability = _build_capability("research")
    assert capability is not None

    responses = [
        ToolCallPart(
            "skill_research_read_file",
            {"path": "console.md"},
            "call-missing-path",
        ),
        ToolCallPart(
            "skill_research_read_file",
            {"path": "SKILL.md", "section": "## Console SSH persistante"},
            "call-missing-section",
        ),
        ToolCallPart(
            "skill_research_read_file",
            {
                "path": "SKILL.md",
                "section": "Persistent console: shell, Python, and Git",
            },
            "call-exact-section",
        ),
    ]
    request_count = 0

    def respond(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> ModelResponse:
        nonlocal request_count
        request_count += 1
        if responses:
            return ModelResponse(parts=[responses.pop(0)])
        return ModelResponse(parts=[TextPart(content="done")])

    result = await PydanticAgent(
        FunctionModel(respond),
        capabilities=[capability],
        retries={"tools": 3, "output": 2},
    ).run("Use the console instructions")

    assert result.output == "done"
    assert request_count == 4


def test_galaris_capability_teaches_document_attachment_workflow() -> None:
    guide = " ".join(
        _read_skill_resource("galaris", "SKILL.md", "Long-term memory").split()
    )

    assert '`file_list("document://<uuid>/attachments/")`' in guide
    assert 'path="document://<uuid>/attachments/"' in guide
    assert '`file_copy(source, "document://<uuid>/attachments/")`' in guide
    assert "Viewing the parent document grants attachment reads" in guide
    assert "create, copy, and delete require edit access" in guide
    assert "Attachment changes never create document-content revisions" in guide
    assert (
        "Every actual document-content change creates an immutable restorable content revision"
        in guide
    )


@pytest.mark.asyncio
async def test_runtime_registers_skill_capabilities_with_pydantic_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    capability = object()

    async def fake_build_model(*args: Any, **kwargs: Any) -> object:
        return object()

    class FakePydanticAgent:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(runtime, "build_model_for_llm", fake_build_model)
    monkeypatch.setattr(runtime, "PydanticAgent", FakePydanticAgent)

    agent = runtime.Agent(
        llm=cast(Any, SimpleNamespace()),
        capabilities=[capability],
    )
    await agent.init()

    capabilities = cast(list[Any], captured["capabilities"])
    assert len(capabilities) == 3
    assert capabilities[-1] is capability
