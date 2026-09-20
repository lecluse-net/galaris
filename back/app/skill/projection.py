"""Driver-neutral snapshots of centrally assigned skill trees."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from . import skill_service, storage
from . import learning_service


@dataclass(frozen=True)
class SkillProjectionFile:
    skill_code: str
    relative_path: str
    source: Path
    size: int
    sha256: str


@dataclass(frozen=True)
class SkillProjectionSnapshot:
    agent_id: int
    skill_codes: tuple[str, ...]
    files: tuple[SkillProjectionFile, ...]
    revision: str


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
    for code in assigned_codes:
        inspection = storage.inspect(code)
        if not inspection.valid:
            continue
        for relative, source in storage.iter_skill_files(code):
            sha256 = storage.file_hash(source)
            size = source.stat().st_size
            files.append(
                SkillProjectionFile(
                    skill_code=code,
                    relative_path=relative,
                    source=source,
                    size=size,
                    sha256=sha256,
                )
            )
            digest.update(code.encode())
            digest.update(b"\0")
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(sha256.encode())
    learned = await learning_service.list_injectable(agent_id)
    learned_codes: list[str] = []
    occupied = set(assigned_codes)
    for item in learned:
        if item.code in occupied:
            continue
        occupied.add(item.code)
        learned_codes.append(item.code)
        source = storage.project_learned_markdown(agent_id, item.code, item.markdown)
        sha256 = storage.file_hash(source)
        size = source.stat().st_size
        files.append(
            SkillProjectionFile(
                skill_code=item.code,
                relative_path="SKILL.md",
                source=source,
                size=size,
                sha256=sha256,
            )
        )
        digest.update(item.code.encode())
        digest.update(b"\0SKILL.md\0")
        digest.update(sha256.encode())
    codes = tuple(sorted((*assigned_codes, *learned_codes)))
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
        content = item.source.read_text(encoding="utf-8")
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
