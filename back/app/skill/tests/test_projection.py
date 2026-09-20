from pathlib import Path
from types import SimpleNamespace

import pytest

from app.skill import learning_service, skill_service, storage
from app.skill.projection import build_skill_projection, build_skill_prompt


@pytest.mark.asyncio
async def test_learned_skills_are_projected_in_addition_to_assigned_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "skills"
    assigned = root / "assigned"
    assigned.mkdir(parents=True)
    (assigned / "SKILL.md").write_text(
        "---\nname: assigned\ndescription: Assigned procedure.\n---\n\nAssigned.\n",
        encoding="utf-8",
    )
    learned_markdown = (
        "---\n"
        "name: learned-agent-check\n"
        "description: Learned verification procedure.\n"
        "---\n\nRun the learned check.\n"
    )

    async def assigned_codes(_agent_id: int) -> list[str]:
        return ["assigned"]

    async def learned_skills(_agent_id: int) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                code="learned-agent-check",
                markdown=learned_markdown,
            )
        ]

    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))
    monkeypatch.setattr(skill_service, "get_assigned_codes", assigned_codes)
    monkeypatch.setattr(learning_service, "list_injectable", learned_skills)

    snapshot = await build_skill_projection(7)
    prompt = await build_skill_prompt(7)

    assert snapshot.skill_codes == ("assigned", "learned-agent-check")
    assert [(item.skill_code, item.relative_path) for item in snapshot.files] == [
        ("assigned", "SKILL.md"),
        ("learned-agent-check", "SKILL.md"),
    ]
    assert "Assigned procedure" in prompt
    assert "Learned verification procedure" in prompt
    assert (root / ".learned" / "7" / "learned-agent-check" / "SKILL.md").is_file()
