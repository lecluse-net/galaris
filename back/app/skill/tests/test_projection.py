from pathlib import Path
from types import SimpleNamespace

import pytest

from app.skill import learning_service, skill_service, storage
from app.skill.projection import build_skill_projection, build_skill_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["hash", "prompt"])
async def test_skill_projection_keeps_other_requests_running(tmp_path, monkeypatch, stage):
    import asyncio
    from threading import Event
    from unittest.mock import AsyncMock

    root = tmp_path / 'skills'
    source = root / 'synthetic' / 'SKILL.md'
    source.parent.mkdir(parents=True)
    source.write_text('---\nname: synthetic\ndescription: Synthetic procedure.\n---\n\nSynthetic instructions.\n')
    monkeypatch.setattr(type(storage.settings), 'GALARIS_SKILLS_ROOT', str(root))
    monkeypatch.setattr(skill_service, 'get_assigned_codes', AsyncMock(return_value=['synthetic']))
    monkeypatch.setattr(learning_service, 'list_injectable', AsyncMock(return_value=[]))
    entered, released = Event(), Event()
    armed = [False]
    original_hash, original_read = storage.file_hash, Path.read_text

    def wait_for_other_request():
        entered.set()
        assert released.wait(3), 'Skill filesystem work blocked unrelated asynchronous requests'

    def file_hash(path):
        if stage == 'hash':
            wait_for_other_request()
        result = original_hash(path)
        armed[0] = True
        return result

    def read_text(path, *args, **kwargs):
        if stage == 'prompt' and path == source and armed[0]:
            wait_for_other_request()
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(storage, 'file_hash', file_hash)
    monkeypatch.setattr(Path, 'read_text', read_text)

    async def unrelated_request():
        while not entered.is_set():
            await asyncio.sleep(0.001)
        released.set()

    async with asyncio.TaskGroup() as group:
        other = group.create_task(unrelated_request())
        try:
            result = await build_skill_prompt(7)
        finally:
            if not entered.is_set():
                other.cancel()
    assert 'Synthetic instructions.' in result


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
    assert (await build_skill_projection(7)).revision == snapshot.revision
    source = assigned / "SKILL.md"
    source.write_text(source.read_text() + "\nChanged synthetic procedure.\n")
    refreshed = await build_skill_projection(7)
    assert refreshed.revision != snapshot.revision
    assert "Changed synthetic procedure." in await build_skill_prompt(7)
