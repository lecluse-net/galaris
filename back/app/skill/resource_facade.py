"""Authorized file-resource facade for centrally managed skill packages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict, cast

from loguru import logger

from core.database import get_db

from . import skill_service, storage
from .schemas import SkillCreate


SKILL_MANAGEMENT_TOOL_CODE = "skill_management"


class SkillResourceSummary(TypedDict):
    code: str
    label: str
    system: bool
    available: bool
    valid: bool
    description: str | None
    file_count: int
    total_size: int
    modified_at: str | None


async def can_manage_skill_resources(agent_id: int) -> bool:
    """Return whether the agent still has the restricted management package."""

    from app.connection import connection_service

    return await connection_service.has_active_tool_connection(
        agent_id=agent_id,
        tool_code=SKILL_MANAGEMENT_TOOL_CODE,
    )


async def require_skill_management_access(agent_id: int) -> None:
    if not await can_manage_skill_resources(agent_id):
        raise PermissionError(
            "An active skill_management connection is required to access skill files."
        )


async def list_skill_resources(
    *,
    actor_agent_id: int,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
) -> list[SkillResourceSummary]:
    await require_skill_management_access(actor_agent_id)
    folded_query = query.strip().casefold()
    summaries: list[SkillResourceSummary] = []
    for record in await skill_service.get_all():
        inspection = storage.inspect(record.code)
        if folded_query and folded_query not in " ".join(
            (record.code, record.label, inspection.description or "")
        ).casefold():
            continue
        summaries.append(
            {
                "code": record.code,
                "label": record.label,
                "system": record.system,
                "available": inspection.available,
                "valid": inspection.valid,
                "description": inspection.description,
                "file_count": inspection.file_count,
                "total_size": inspection.total_size,
                "modified_at": (
                    record.updated_at.isoformat()
                    if record.updated_at is not None
                    else record.created_at.isoformat()
                ),
            }
        )
    start = max(0, offset)
    return summaries[start : start + max(1, min(limit, 501))]


async def get_skill_resource(
    code: str,
    *,
    actor_agent_id: int,
) -> SkillResourceSummary | None:
    await require_skill_management_access(actor_agent_id)
    normalized = storage.validate_code(code)
    record = await skill_service.get_by_code(normalized)
    if record is None:
        return None
    inspection = storage.inspect(normalized)
    return {
        "code": record.code,
        "label": record.label,
        "system": record.system,
        "available": inspection.available,
        "valid": inspection.valid,
        "description": inspection.description,
        "file_count": inspection.file_count,
        "total_size": inspection.total_size,
        "modified_at": (
            record.updated_at.isoformat()
            if record.updated_at is not None
            else record.created_at.isoformat()
        ),
    }


async def list_skill_files(
    code: str,
    *,
    actor_agent_id: int,
) -> list[storage.StoredSkillFile]:
    summary = await get_skill_resource(code, actor_agent_id=actor_agent_id)
    if summary is None or not summary["available"]:
        raise FileNotFoundError(code)
    return storage.list_files(code)


async def read_skill_file(
    code: str,
    path: str,
    *,
    actor_agent_id: int,
) -> storage.SkillFileData:
    summary = await get_skill_resource(code, actor_agent_id=actor_agent_id)
    if summary is None or not summary["available"]:
        raise FileNotFoundError(code)
    return storage.read_file(code, path)


async def _touch(code: str) -> None:
    record = await skill_service.get_by_code(code)
    if record is None:
        raise FileNotFoundError(code)
    record.updated_at = cast(Any, datetime.now(timezone.utc))
    await get_db().commit()


async def create_skill_file(
    code: str,
    path: str,
    content: bytes,
    *,
    actor_agent_id: int,
) -> storage.SkillFileData:
    await require_skill_management_access(actor_agent_id)
    normalized = storage.validate_code(code)
    record = await skill_service.get_by_code(normalized)
    if record is None:
        if path != "SKILL.md":
            raise FileNotFoundError(
                f"Create galaris://skill/{normalized}/SKILL.md before auxiliary files."
            )
        try:
            markdown = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("SKILL.md must be UTF-8.") from exc
        await skill_service.create(
            SkillCreate(code=normalized, label=normalized, markdown=markdown)
        )
        logger.info(
            "Skill created through file facade: code={} actor_agent_id={}",
            normalized,
            actor_agent_id,
        )
        return storage.read_file(normalized, path)
    await storage.write_file(normalized, path, content, overwrite=False)
    await _touch(normalized)
    logger.info(
        "Skill file created: code={} path={} actor_agent_id={}",
        normalized,
        path,
        actor_agent_id,
    )
    return storage.read_file(normalized, path)


async def write_skill_file(
    code: str,
    path: str,
    content: bytes,
    *,
    actor_agent_id: int,
    expected_revision: int | None = None,
) -> storage.SkillFileData:
    summary = await get_skill_resource(code, actor_agent_id=actor_agent_id)
    if summary is None or not summary["available"]:
        raise FileNotFoundError(code)
    result = await storage.write_file(
        code,
        path,
        content,
        overwrite=True,
        expected_revision=expected_revision,
    )
    await _touch(code)
    logger.info(
        "Skill file written: code={} path={} actor_agent_id={}",
        code,
        path,
        actor_agent_id,
    )
    return result


async def append_skill_file(
    code: str,
    path: str,
    content: str,
    *,
    actor_agent_id: int,
) -> storage.SkillFileData:
    summary = await get_skill_resource(code, actor_agent_id=actor_agent_id)
    if summary is None or not summary["available"]:
        raise FileNotFoundError(code)
    result = await storage.append_file(code, path, content)
    await _touch(code)
    logger.info(
        "Skill file appended: code={} path={} actor_agent_id={}",
        code,
        path,
        actor_agent_id,
    )
    return result


async def delete_skill_file(
    code: str,
    path: str,
    *,
    actor_agent_id: int,
) -> storage.SkillFileData:
    summary = await get_skill_resource(code, actor_agent_id=actor_agent_id)
    if summary is None or not summary["available"]:
        raise FileNotFoundError(code)
    result = await storage.delete_file(code, path)
    await _touch(code)
    logger.info(
        "Skill file deleted: code={} path={} actor_agent_id={}",
        code,
        path,
        actor_agent_id,
    )
    return result


async def move_skill_file(
    code: str,
    source_path: str,
    destination_path: str,
    *,
    actor_agent_id: int,
    overwrite: bool,
) -> storage.SkillFileData:
    summary = await get_skill_resource(code, actor_agent_id=actor_agent_id)
    if summary is None or not summary["available"]:
        raise FileNotFoundError(code)
    result = await storage.move_file(
        code,
        source_path,
        destination_path,
        overwrite=overwrite,
    )
    await _touch(code)
    logger.info(
        "Skill file moved: code={} source={} destination={} actor_agent_id={}",
        code,
        source_path,
        destination_path,
        actor_agent_id,
    )
    return result


__all__ = [
    "SKILL_MANAGEMENT_TOOL_CODE",
    "SkillResourceSummary",
    "append_skill_file",
    "can_manage_skill_resources",
    "create_skill_file",
    "delete_skill_file",
    "get_skill_resource",
    "list_skill_files",
    "list_skill_resources",
    "move_skill_file",
    "read_skill_file",
    "require_skill_management_access",
    "write_skill_file",
]
