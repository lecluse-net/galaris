"""Driver-neutral snapshots of centrally assigned skill trees."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from core.util import complete_io

from . import skill_service, storage
from . import interface
from .contracts import SkillPackageRef, runtime_skill_name


@dataclass(frozen=True)
class SkillProjectionFile:
    skill_code: str
    relative_path: str
    source: Path
    size: int
    sha256: str
    source_code: str | None = None
    owner_agent_id: int | None = None
    package_id: int | None = None


@dataclass(frozen=True)
class SkillProjectionSnapshot:
    agent_id: int
    skill_codes: tuple[str, ...]
    files: tuple[SkillProjectionFile, ...]
    revision: str


def _assigned_files(code: str) -> list[SkillProjectionFile]:
    if not storage.inspect(code).valid:
        return []
    files: list[SkillProjectionFile] = []
    for relative, source in storage.iter_skill_files(code):
        digest = storage.file_hash(source)
        files.append(SkillProjectionFile(skill_code=code, relative_path=relative, source=source,
                                        size=source.stat().st_size, sha256=digest))
    return files


async def build_skill_projection(
    agent_id: int,
    *,
    skill_codes: list[str] | None = None,
) -> SkillProjectionSnapshot:
    """Freeze assigned, valid skill files for a runtime-specific projector."""

    assigned = (
        skill_codes
        if skill_codes is not None
        else await skill_service.get_assigned_codes(agent_id)
    )
    assigned_codes = tuple(sorted(set(assigned)))
    files: list[SkillProjectionFile] = []
    digest = hashlib.sha256()
    occupied: set[str] = set()
    actual_codes: list[str] = []
    runtime_names: set[str] = set()
    for code in assigned_codes:
        name = runtime_skill_name(code, "generic", code, occupied)
        actual_codes.append(name)
        for item in await complete_io(_assigned_files, code):
            if name != code and item.relative_path == "SKILL.md":
                source = await complete_io(storage.project_runtime_markdown, agent_id, name,
                                           await complete_io(item.source.read_text, encoding="utf-8"))
                runtime_names.add(name)
                item = SkillProjectionFile(name, item.relative_path, source, source.stat().st_size,
                                           await complete_io(storage.file_hash, source), source_code=code)
            elif name != code:
                item = SkillProjectionFile(name, item.relative_path, item.source, item.size, item.sha256, source_code=code)
            files.append(item)
            digest.update(code.encode())
            digest.update(b"\0")
            digest.update(item.relative_path.encode())
            digest.update(b"\0")
            digest.update(item.sha256.encode())
    for package in await interface.personal_packages(agent_id):
        if not (await complete_io(storage.inspect, package.code, owner_agent_id=agent_id)).valid:
            continue
        name = runtime_skill_name(package.code, "personal", str(package.id), occupied)
        actual_codes.append(name)
        def personal_files(package: SkillPackageRef = package, name: str = name) -> list[SkillProjectionFile]:
            result: list[SkillProjectionFile] = []
            for relative, source in storage.iter_skill_files(package.code, owner_agent_id=agent_id):
                if relative == "SKILL.md" and name != package.code:
                    source = storage.project_runtime_markdown(agent_id, name, source.read_text(encoding="utf-8"))
                    runtime_names.add(name)
                result.append(SkillProjectionFile(name, relative, source, source.stat().st_size,
                    storage.file_hash(source), source_code=package.code, owner_agent_id=agent_id, package_id=package.id))
            return result
        for item in await complete_io(personal_files):
            files.append(item)
            digest.update(f"personal:{package.id}:{package.revision}:{item.relative_path}:{item.sha256}".encode())
    await complete_io(storage.prune_runtime_markdown, agent_id, runtime_names)
    codes = tuple(sorted(actual_codes))
    return SkillProjectionSnapshot(
        agent_id=agent_id,
        skill_codes=codes,
        files=tuple(files),
        revision=digest.hexdigest(),
    )


async def build_skill_prompt(agent_id: int, *, max_bytes: int = 200_000) -> str:
    """Render bounded SKILL.md instructions for Harnesses without a filesystem projector."""

    snapshot = await build_skill_projection(agent_id)
    parts: list[str] = []
    used = 0
    for item in snapshot.files:
        if item.relative_path != "SKILL.md":
            continue
        content = await complete_io(item.source.read_text, encoding="utf-8")
        block = f"## Skill: {item.skill_code}\n\n{content.strip()}"
        encoded = block.encode("utf-8")
        if used + len(encoded) > max_bytes:
            break
        parts.append(block)
        used += len(encoded)
    if not parts:
        return ""
    return "# Galaris skills\n\n" + "\n\n".join(parts)


__all__ = [
    "SkillProjectionFile",
    "SkillProjectionSnapshot",
    "build_skill_projection",
    "build_skill_prompt",
]
