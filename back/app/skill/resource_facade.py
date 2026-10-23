"""Compatibility exports delegating to the single Skills authorization boundary."""

from . import interface, storage
from .contracts import SkillPackageCreate, SkillScope, SkillPackageRef

SKILL_MANAGEMENT_TOOL_CODE = 'skills'


async def can_manage_skill_resources(agent_id: int) -> bool:
    return await interface.get_agent_scope(agent_id) != SkillScope.USAGE


async def require_skill_management_access(agent_id: int) -> None:
    if not await can_manage_skill_resources(agent_id):
        raise PermissionError('An active Skills management delegation is required')


async def _ref(code: str, agent_id: int, *, write: bool = False) -> SkillPackageRef:
    return await interface.resolve_package(code, actor_agent_id=agent_id, write=write,
        administration=await interface.get_agent_scope(agent_id) == SkillScope.ALL)


async def list_skill_resources(*, actor_agent_id: int, query: str = '', offset: int = 0, limit: int = 100) -> list[dict[str, object]]:
    admin = await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL
    folded = query.strip().casefold()
    summaries = await interface.list_package_summaries(actor_agent_id=actor_agent_id,
        administration=admin, kind='generic', offset=0 if folded else offset,
        limit=501 if folded else min(limit, 500))
    if not folded:
        return summaries
    result = [item for item in summaries if folded in ' '.join(
        str(item[key] or '') for key in ('code', 'label', 'description')).casefold()]
    return result[offset:offset + min(limit, 500)]


async def get_skill_resource(code: str, *, actor_agent_id: int) -> dict[str, object] | None:
    rows = await interface.list_package_summaries(actor_agent_id=actor_agent_id,
        administration=await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL,
        kind='generic', code=code, limit=1)
    return rows[0] if rows else None


async def list_skill_files(code: str, *, actor_agent_id: int) -> list[storage.StoredSkillFile]:
    reference = await _ref(code, actor_agent_id)
    return await interface.package_files(reference.id, actor_agent_id=actor_agent_id,
        administration=await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL)


async def read_skill_file(code: str, path: str, *, actor_agent_id: int) -> storage.SkillFileData:
    reference = await _ref(code, actor_agent_id)
    return await interface.read_package_file(reference.id, path, actor_agent_id=actor_agent_id,
        administration=await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL)


async def create_skill_file(code: str, path: str, content: bytes, *, actor_agent_id: int) -> storage.SkillFileData:
    try:
        reference = await _ref(code, actor_agent_id, write=True)
    except FileNotFoundError:
        if path != 'SKILL.md':
            raise
        reference = await interface.create_package(SkillPackageCreate(code=code, label=code,
            markdown=content.decode('utf-8')), actor_agent_id=actor_agent_id, generic=True)
        return await read_skill_file(code, path, actor_agent_id=actor_agent_id)
    return await interface.mutate_file(reference.id, path, actor_agent_id=actor_agent_id,
        operation='create', content=content, administration=await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL)


async def write_skill_file(code: str, path: str, content: bytes, *, actor_agent_id: int,
                           expected_revision: int | None = None) -> storage.SkillFileData:
    reference = await _ref(code, actor_agent_id, write=True)
    return await interface.mutate_file(reference.id, path, actor_agent_id=actor_agent_id,
        operation='write', content=content, expected_revision=expected_revision,
        administration=await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL)


async def append_skill_file(code: str, path: str, content: str, *, actor_agent_id: int) -> storage.SkillFileData:
    reference = await _ref(code, actor_agent_id, write=True)
    return await interface.mutate_file(reference.id, path, actor_agent_id=actor_agent_id,
        operation='append', content=content.encode('utf-8'), administration=await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL)


async def delete_skill_file(code: str, path: str, *, actor_agent_id: int) -> storage.SkillFileData:
    reference = await _ref(code, actor_agent_id, write=True)
    return await interface.mutate_file(reference.id, path, actor_agent_id=actor_agent_id,
        operation='delete', administration=await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL)


async def move_skill_file(code: str, source_path: str, destination_path: str, *, actor_agent_id: int,
                          overwrite: bool) -> storage.SkillFileData:
    reference = await _ref(code, actor_agent_id, write=True)
    return await interface.mutate_file(reference.id, source_path, actor_agent_id=actor_agent_id,
        operation='move', destination=destination_path, overwrite=overwrite,
        administration=await interface.get_agent_scope(actor_agent_id) == SkillScope.ALL)
