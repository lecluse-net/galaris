from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.agent.models import Agent
from app.skill import storage
from bridge.hermes import skill_sync


@pytest.fixture(autouse=True)
def no_learned_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.skill import learning_service

    monkeypatch.setattr(learning_service, "list_injectable", AsyncMock(return_value=[]))


def test_collect_managed_files_reads_bundled_system_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills")
    )

    files = skill_sync.collect_managed_files(["galaris"])

    assert set(files) == {"data/skills/galaris/galaris/SKILL.md"}
    assert files["data/skills/galaris/galaris/SKILL.md"]["source"] == (
        storage.SYSTEM_SKILLS_ROOT / "galaris/SKILL.md"
    )
    assert not (tmp_path / "skills/galaris").exists()


@pytest.mark.asyncio
async def test_system_skill_rebuilds_galaris_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills")
    )

    async def assigned(_agent_id: int) -> list[str]:
        return ["galaris"]

    monkeypatch.setattr(skill_sync, "_assigned_codes", assigned)

    class Manager:
        def __init__(self) -> None:
            self.uploaded: list[str] = []
            self.purged: list[str] = []
            self.manifest = ""

        async def delete_agent_tree(self, _agent: str, path: str) -> bool:
            self.purged.append(path)
            return True

        async def upload_agent_file_from(self, _agent: str, path: str, _source: Path) -> int:
            self.uploaded.append(path)
            return 1

        async def write_agent_file(self, _agent: str, _path: str, content: str) -> None:
            self.manifest = content

    manager = Manager()
    agent = cast(Agent, SimpleNamespace(id=7, code="alice"))

    result = await skill_sync.sync_managed_skills(agent, cast(Any, manager))

    assert manager.uploaded == ["data/skills/galaris/galaris/SKILL.md"]
    assert manager.purged == [
        "data/skills/galaris",
        "data/skills/galaris-managed",
    ]
    assert '"data/skills/galaris/galaris/SKILL.md"' in manager.manifest
    assert result == {"skills": 1, "uploaded": 1, "unchanged": 0, "deleted": 2}


@pytest.mark.asyncio
async def test_sync_managed_skills_purges_tree_before_rebuilding_assigned_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills")
    )
    source = tmp_path / "skills/research"
    (source / "scripts").mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: research\ndescription: Research procedure.\n---\n", encoding="utf-8"
    )
    (source / "scripts/run.py").write_text("print('ok')\n", encoding="utf-8")

    async def assigned(_agent_id: int) -> list[str]:
        return ["research"]

    monkeypatch.setattr(skill_sync, "_assigned_codes", assigned)

    class Manager:
        def __init__(self) -> None:
            self.files = {
                "data/skills/galaris/removed-skill/SKILL.md",
                "data/skills/galaris/research/obsolete.txt",
                "data/skills/galaris-managed/legacy.txt",
            }
            self.events: list[tuple[str, str]] = []
            self.manifest = ""

        async def delete_agent_tree(self, _agent: str, path: str) -> bool:
            self.events.append(("purge", path))
            prefix = f"{path}/"
            existing = any(file.startswith(prefix) for file in self.files)
            self.files = {file for file in self.files if not file.startswith(prefix)}
            return existing

        async def upload_agent_file_from(self, _agent: str, path: str, _source: Path) -> int:
            self.events.append(("upload", path))
            self.files.add(path)
            return 1

        async def write_agent_file(self, _agent: str, path: str, content: str) -> None:
            self.events.append(("write", path))
            self.files.add(path)
            self.manifest = content

    manager = Manager()
    agent = cast(Agent, SimpleNamespace(id=7, code="alice"))

    result = await skill_sync.sync_managed_skills(agent, cast(Any, manager))

    assert manager.events[:2] == [
        ("purge", "data/skills/galaris"),
        ("purge", "data/skills/galaris-managed"),
    ]
    assert manager.files == {
        "data/skills/galaris/.galaris-manifest.json",
        "data/skills/galaris/research/SKILL.md",
        "data/skills/galaris/research/scripts/run.py",
    }
    assert not any("removed-skill" in path for path in manager.files)
    assert '"data/skills/galaris/research/SKILL.md"' in manager.manifest
    assert result == {"skills": 1, "uploaded": 2, "unchanged": 0, "deleted": 2}
