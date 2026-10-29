from pathlib import Path
from types import SimpleNamespace

import pytest

from app.skill import skill_service, storage
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



@pytest.fixture(autouse=True)
def no_personal_packages_in_filesystem_unit_tests(monkeypatch):
    from unittest.mock import AsyncMock
    from app.skill import interface
    monkeypatch.setattr(interface, 'personal_packages', AsyncMock(return_value=[]))
