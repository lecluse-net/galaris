"""Canonical Skill URI adapter. All resource rights and writes belong to app.skill."""

import base64
from dataclasses import dataclass
import mimetypes
from urllib.parse import quote

from app.skill import interface
from app.skill.contracts import SkillScope, SkillPackageRef
from .resource_contracts import (ResourceContext, ResourceDescriptor, ResourceListing, ResourceMutation,
    ResourceRead, ResourceSearchHit, ResourceSearchResult)
from .resource_uri import ResourceUri, ResourceUriError


@dataclass(frozen=True)
class SkillUri:
    personal: bool
    owner: int | None = None
    code: str | None = None
    path: str | None = None

    @property
    def root(self) -> str:
        prefix = 'galaris://skill/'
        if self.personal:
            prefix += 'personnal/'
            if self.owner is not None:
                prefix += f'{self.owner}/'
        if self.code:
            prefix += f'{self.code}/'
        return prefix


def route(reference: ResourceUri) -> SkillUri:
    if reference.scheme != 'galaris' or reference.segments[:1] != ('skill',):
        raise PermissionError('Business snapshots are read-only; only galaris://skill/ files support mutations')
    parts = list(reference.segments[1:])
    personal = bool(parts and parts[0] == 'personnal')
    owner = None
    if personal:
        parts.pop(0)
        if parts:
            value = parts.pop(0)
            if not value.isdecimal() or int(value) < 1:
                raise ResourceUriError('A personal skill owner must be a positive agent ID')
            owner = int(value)
    code = parts.pop(0) if parts else None
    if code is not None:
        from app.skill import storage
        storage.validate_code(code)
    return SkillUri(personal, owner, code, '/'.join(parts) if parts else None)


async def administrative(ctx: ResourceContext) -> bool:
    return await interface.get_agent_scope(ctx.agent_id) in (SkillScope.TEAM, SkillScope.ALL)


async def _owner(ctx: ResourceContext, target: SkillUri) -> None:
    if target.personal and target.owner is not None and target.owner != ctx.agent_id:
        try:
            await interface.require_agent_administration(ctx.agent_id, target.owner)
        except PermissionError as exc:
            raise FileNotFoundError('Skill not found') from exc


async def _ref(ctx: ResourceContext, target: SkillUri, *, write: bool = False) -> SkillPackageRef:
    await _owner(ctx, target)
    if target.code is None:
        raise ResourceUriError('An exact skill package is required')
    return await interface.resolve_package(target.code, actor_agent_id=ctx.agent_id,
        owner_agent_id=target.owner, write=write, administration=await administrative(ctx))


async def info(ctx: ResourceContext, reference: ResourceUri) -> ResourceDescriptor:
    target = route(reference)
    await _owner(ctx, target)
    scope = await interface.get_agent_scope(ctx.agent_id)
    if target.code is None:
        can_create = (scope != SkillScope.USAGE and target.owner in (None, ctx.agent_id)) if target.personal else scope == SkillScope.ALL
        return ResourceDescriptor(uri=target.root, name=('Personal skills' if target.personal else 'Skills')
            if target.owner is None else f'Agent {target.owner}', is_collection=True,
            capabilities=['info', 'list', 'search', *(['create'] if can_create else [])])
    package = await _ref(ctx, target)
    metadata = await interface.describe_package(package.id, actor_agent_id=ctx.agent_id,
                                                 administration=await administrative(ctx))
    mutable = not metadata['system'] and (scope == SkillScope.ALL or
        (scope in (SkillScope.PERSONAL, SkillScope.TEAM) and target.owner == ctx.agent_id)
        or (scope == SkillScope.TEAM and target.owner is not None))
    if target.path is None:
        return ResourceDescriptor(uri=target.root, name=str(metadata['label']), is_collection=True,
            revision=package.revision, metadata=metadata,
            capabilities=['info', 'list', 'search', *(['create'] if mutable else [])])
    item = next((item for item in await interface.package_files(package.id, actor_agent_id=ctx.agent_id,
        administration=await administrative(ctx)) if item['path'] == target.path), None)
    if item is None:
        raise FileNotFoundError('Skill file not found')
    return ResourceDescriptor(uri=target.root + '/'.join(quote(part, safe='-._~') for part in item['path'].split('/')),
        name=item['name'], size=item['size'], revision=package.revision,
        media_type=mimetypes.guess_type(item['path'])[0] or 'application/octet-stream',
        metadata={**metadata, 'path': item['path']},
        capabilities=['info', 'read', *(['copy'] if target.owner is None else []),
            *(['write', *(['append', 'edit'] if item['text'] else []),
               *(['delete', 'move'] if item['path'] != 'SKILL.md' else [])] if mutable else [])])


async def listing(ctx: ResourceContext, reference: ResourceUri, *, max_entries: int, cursor: str | None) -> ResourceListing:
    target = route(reference)
    await _owner(ctx, target)
    offset = int(cursor or '0')
    limit = max(1, min(max_entries, 500))
    if offset < 0:
        raise ValueError('Invalid Skills cursor')
    entries: list[ResourceDescriptor] = []
    admin = await administrative(ctx)
    scope = await interface.get_agent_scope(ctx.agent_id)
    if target.code is not None:
        package = await _ref(ctx, target)
        files = await interface.package_files(package.id, actor_agent_id=ctx.agent_id, administration=admin)
        for item in files[offset:offset + limit + 1]:
            from .resource_uri import parse_resource_uri
            entries.append(await info(ctx, parse_resource_uri(target.root + '/'.join(quote(part, safe='-._~') for part in item['path'].split('/')))))
    elif target.personal and target.owner is None:
        owners = await interface.personal_owners(ctx.agent_id, offset, limit + 1)
        entries = [ResourceDescriptor(uri=f'galaris://skill/personnal/{owner}/', name=f'Agent {owner}',
            is_collection=True, capabilities=['info', 'list', 'search']) for owner in owners]
    else:
        # Keep the branch as a separate collection, never a generic package row.
        branch = not target.personal and offset == 0
        if branch:
            entries.append(ResourceDescriptor(uri='galaris://skill/personnal/', name='Personal skills',
                is_collection=True, capabilities=['info', 'list', 'search']))
        packages = await interface.list_packages(actor_agent_id=ctx.agent_id, administration=admin,
            kind='personal' if target.personal else 'generic', owner_agent_id=target.owner,
            include_unavailable=scope != SkillScope.USAGE,
            offset=max(0, offset - (0 if target.personal else 1)), limit=limit + 1)
        from .resource_uri import parse_resource_uri
        for item in packages:
            entries.append(await info(ctx, parse_resource_uri(item.uri)))
    truncated = len(entries) > limit
    return ResourceListing(uri=str(reference), entries=entries[:limit], truncated=truncated,
                           next_cursor=str(offset + limit) if truncated else None)


async def read(ctx: ResourceContext, reference: ResourceUri, *, offset: int, max_chars: int) -> ResourceRead:
    target = route(reference)
    package = await _ref(ctx, target)
    if target.path is None:
        raise IsADirectoryError(str(reference))
    data = await interface.read_package_file(package.id, target.path, actor_agent_id=ctx.agent_id,
                                               administration=await administrative(ctx))
    if not data.text:
        if len(data.content) > 512 * 1024:
            raise ValueError('Binary skill file is too large for inline reading')
        return ResourceRead(uri=str(reference), content=base64.b64encode(data.content).decode(),
            encoding='base64', start=0, end=len(data.content), total=len(data.content), revision=data.revision)
    content = data.content.decode('utf-8')
    start = max(0, min(offset, len(content)))
    end = min(len(content), start + max_chars)
    return ResourceRead(uri=str(reference), content=content[start:end], start=start, end=end,
                        total=len(content), next_offset=end if end < len(content) else None, revision=data.revision)


async def mutate(ctx: ResourceContext, reference: ResourceUri, content: bytes = b'', *,
                 operation: str, expected_revision: int | None = None) -> ResourceMutation:
    target = route(reference)
    await _owner(ctx, target)
    if target.code is None or target.path is None:
        raise ResourceUriError('Create a package using its exact SKILL.md URI')
    try:
        package = await _ref(ctx, target, write=True)
    except FileNotFoundError:
        if operation != 'create' or target.path != 'SKILL.md':
            raise
        if target.personal and target.owner != ctx.agent_id:
            raise PermissionError('A new personal skill belongs to its authenticated creator')
        from app.skill.contracts import SkillPackageCreate
        package = await interface.create_package(SkillPackageCreate(code=target.code,
            label=target.code, markdown=content.decode('utf-8')), actor_agent_id=ctx.agent_id,
            generic=not target.personal)
        return ResourceMutation(uri=package.uri + 'SKILL.md', operation='create', state='created',
                                size=len(content), revision=package.revision)
    from typing import cast, Literal
    data = await interface.mutate_file(package.id, target.path, actor_agent_id=ctx.agent_id,
        operation=cast(Literal['create', 'write', 'append', 'delete'], operation), content=content,
        expected_revision=expected_revision, administration=await administrative(ctx), expected_identity=package)
    return ResourceMutation(uri=str(reference), operation=cast(Literal['create', 'write', 'append', 'delete'], operation),
                            state={'create': 'created', 'write': 'written', 'append': 'appended', 'delete': 'deleted'}[operation],
                            size=len(data.content), revision=data.revision)


async def move(ctx: ResourceContext, source: ResourceUri, destination: ResourceUri, *, overwrite: bool) -> ResourceMutation:
    src, dst = route(source), route(destination)
    if (src.personal, src.owner, src.code) != (dst.personal, dst.owner, dst.code) or src.path is None:
        raise PermissionError('Skill files can only move within the same package; use explicit ownership release for conversion')
    package = await _ref(ctx, src, write=True)
    path = dst.path or src.path.rsplit('/', 1)[-1]
    data = await interface.mutate_file(package.id, src.path, actor_agent_id=ctx.agent_id,
        operation='move', destination=path, overwrite=overwrite, administration=await administrative(ctx), expected_identity=package)
    return ResourceMutation(uri=dst.root + path, source_uri=str(source), operation='move', state='moved', revision=data.revision)


async def check_copy(ctx: ResourceContext, source: ResourceUri, destination: ResourceUri) -> None:
    if source.scheme != 'galaris' or source.segments[:2] != ('skill', 'personnal'):
        return
    src = route(source)
    await _ref(ctx, src)
    if destination.scheme != 'galaris' or destination.segments[:2] != ('skill', 'personnal'):
        raise PermissionError('Personal skill resources cannot be exported or shared')
    dst = route(destination)
    if (src.owner, src.code) != (dst.owner, dst.code):
        raise PermissionError('Personal skill resources cannot be copied to another package')


async def file_bytes(ctx: ResourceContext, reference: ResourceUri) -> bytes:
    target = route(reference)
    package = await _ref(ctx, target)
    if target.path is None:
        raise IsADirectoryError(str(reference))
    return (await interface.read_package_file(package.id, target.path, actor_agent_id=ctx.agent_id,
        administration=await administrative(ctx))).content


async def search(ctx: ResourceContext, reference: ResourceUri, query: str, *, mode: str,
                 max_results: int, cursor: str | None) -> ResourceSearchResult:
    target = route(reference)
    await _owner(ctx, target)
    package_offset, file_offset = map(int, (cursor or '0/0').split('/'))
    if min(package_offset, file_offset) < 0:
        raise ValueError('Invalid Skills search cursor')
    admin = await administrative(ctx)
    packages = [await _ref(ctx, target)] if target.code else await interface.list_packages(
        actor_agent_id=ctx.agent_id, administration=admin,
        include_unavailable=await interface.get_agent_scope(ctx.agent_id) != SkillScope.USAGE,
        kind='personal' if target.personal else None, owner_agent_id=target.owner,
        offset=package_offset, limit=50)
    hits: list[ResourceSearchHit] = []
    scanned, size = 0, 0
    next_cursor = None
    from .resource_uri import parse_resource_uri
    for index, package in enumerate(packages):
        files = await interface.package_files(package.id, actor_agent_id=ctx.agent_id, administration=admin)
        for file_index, item in enumerate(files):
            if file_index < (file_offset if index == 0 else 0):
                continue
            if len(hits) >= max_results or scanned >= 2000 or size >= 4 * 1024 * 1024:
                next_cursor = f'{package_offset + index}/{file_index}'
                break
            scanned += 1
            excerpt = ''
            found = query.casefold() in (package.code + '/' + item['path']).casefold()
            if mode != 'name' and item['text'] and item['size'] <= 1024 * 1024:
                data = await interface.read_package_file(package.id, item['path'], actor_agent_id=ctx.agent_id, administration=admin)
                size += len(data.content)
                text = data.content.decode('utf-8', errors='replace')
                position = text.casefold().find(query.casefold())
                found = found or position >= 0
                if position >= 0:
                    excerpt = text[max(0, position - 80):position + 240]
            if found:
                uri = parse_resource_uri(package.uri + '/'.join(quote(part, safe='-._~') for part in item['path'].split('/')))
                hits.append(ResourceSearchHit(resource=await info(ctx, uri), excerpt=excerpt))
        if next_cursor:
            break
    if next_cursor is None and target.code is None and len(packages) == 50:
        next_cursor = f'{package_offset + 50}/0'
    from typing import cast, Literal
    return ResourceSearchResult(uri=str(reference), query=query, mode=cast(Literal['name', 'text', 'semantic'], mode),
        hits=hits, truncated=next_cursor is not None, next_cursor=next_cursor)
