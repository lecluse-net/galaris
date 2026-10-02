"""Immediate resource catalogue, independent of crawlers and Dream."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import cast
from uuid import UUID

from sqlalchemy import Text, and_, exists, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.connection import Connection, ConnectionParam
from app.connection.facade import effective_param_value_expression
from app.tools import ToolModel
from app.tools.contracts import FILE_INDEXING_PARAM, FileIndexingMode
from app.memory import project_catalogue_entry, link_catalogue_entries, catalogue_projection_write, detach_catalogue_parent_links
from core.database import get_db

from .bridges import get_bridge
from .file_share_service import resolve_resource_transport_with_service
from .models import FileCatalogEntry
from .resource_contracts import ResourceContext, ResourceDescriptor
from .resource_uri import PROTOCOL_SCHEMES, NATIVE_RESOURCE_SCHEMES, parse_resource_uri


def indexing_mode_expression() -> ColumnElement[str | None]:
    return effective_param_value_expression(ToolModel.global_params, ToolModel.connection_schema,
                                           Connection.id, FILE_INDEXING_PARAM)


async def effective_file_indexing_mode(agent_id: int, tool_code: str) -> FileIndexingMode:
    value = await get_db().scalar(select(indexing_mode_expression()).select_from(Connection).join(
        ToolModel, ToolModel.id == Connection.tool_id,
    ).where(Connection.agent_id == agent_id, Connection.active.is_(True), ToolModel.code == tool_code))
    return cast(FileIndexingMode, value) if value in {"known_uris", "recursive"} else "excluded"


def binding_stamp() -> ColumnElement[str]:
    # Hash encrypted persisted configuration, never decrypted credentials. JSONB
    # has canonical key ordering. Global values and local overrides both matter.
    params = select(func.jsonb_object_agg(ConnectionParam.param_name, ConnectionParam.param_value)).where(
        ConnectionParam.connection_id == Connection.id,
    ).correlate(Connection).scalar_subquery()
    snapshot = func.jsonb_build_array(
        ToolModel.file_share_config, ToolModel.global_params,
        ToolModel.connection_schema, ToolModel.mcp_config, params,
    ).cast(Text)
    return func.encode(func.sha256(func.convert_to(snapshot, "UTF8")), "hex")


def _live_binding() -> ColumnElement[bool]:
    return and_(
        Connection.active.is_(True),
        Connection.agent_id == FileCatalogEntry.agent_id,
        indexing_mode_expression().in_(("known_uris", "recursive")),
        FileCatalogEntry.binding_stamp == binding_stamp(),
    )


def catalogue_access_clause(item_id: InstrumentedAttribute[UUID | None]) -> ColumnElement[bool]:
    # A binding belongs to a connection, not to each of its 100k files. Compute
    # inherited policy and configuration hashes once per connection per query.
    bindings = select(Connection.id, Connection.agent_id, binding_stamp().label("stamp")).join(
        ToolModel, ToolModel.id == Connection.tool_id,
    ).where(Connection.active.is_(True), indexing_mode_expression().in_(("known_uris", "recursive"))).cte().prefix_with("MATERIALIZED", dialect="postgresql")
    return exists(select(FileCatalogEntry.id).join(
        bindings, bindings.c.id == FileCatalogEntry.connection_id,
    ).where(
        FileCatalogEntry.memory_item_id == item_id,
        FileCatalogEntry.present.is_(True), FileCatalogEntry.agent_id == bindings.c.agent_id,
        FileCatalogEntry.binding_stamp == bindings.c.stamp,
    ))


@dataclass(frozen=True)
class ObservationScope:
    connection_id: int
    agent_id: int
    stamp: str
    runtime: str
    started_at: datetime


def descriptor_version(descriptor: dict[str, object]) -> str:
    # Renaming a resource preserves its content analysis. Provider version
    # evidence, media type and size determine the acquisition identity.
    version = {key: descriptor.get(key) for key in (
        "checksum", "etag", "revision", "modified_at", "size", "media_type", "is_collection",
    )}
    return hashlib.sha256(json.dumps(version, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def observation_scope(ctx: ResourceContext, uri: object) -> ObservationScope | None:
    reference = parse_resource_uri(uri, allow_empty=True)
    if reference.scheme in PROTOCOL_SCHEMES or reference.scheme in NATIVE_RESOURCE_SCHEMES - {"console"} or reference.scheme == "mail":
        return None
    db = get_db()
    row = (await db.execute(select(Connection.id, binding_stamp(), ToolModel.file_share_config,
                                  indexing_mode_expression()).join(
        ToolModel, ToolModel.id == Connection.tool_id,
    ).where(Connection.agent_id == ctx.agent_id, Connection.active.is_(True),
            ToolModel.code == reference.scheme))).one_or_none()
    if row is None or row[3] == "excluded":
        return None
    if reference.scheme == "console":
        if row[3] != "known_uris":
            return None
    else:
        config = cast(dict[str, object] | None, row[2])
        service = str(config.get("service", "")) if config else ""
        if not service or service == "mail" or row[3] not in get_bridge(service).indexing_modes:
            return None
        _transport, resolved_service = await resolve_resource_transport_with_service(
            ctx.agent_id, reference.scheme, reference.decoded_locator, language=ctx.language,
        )
        if resolved_service == "messenger":
            return None
    return ObservationScope(int(row[0]), ctx.agent_id, str(row[1]), ctx.runtime,
                            datetime.now(timezone.utc))


async def lock_binding(scope: ObservationScope) -> None:
    key = f"file-catalogue:{scope.connection_id}:{scope.stamp}:{scope.runtime}"
    value = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
    await get_db().execute(select(func.pg_advisory_xact_lock(value)))


async def lock_observation_scopes(scopes: list[ObservationScope]) -> None:
    for scope in sorted(scopes, key=lambda item: (item.connection_id, item.stamp, item.runtime)):
        await lock_binding(scope)


async def current_binding(scope: ObservationScope) -> bool:
    stamp = await get_db().scalar(select(binding_stamp()).select_from(Connection).join(
        ToolModel, ToolModel.id == Connection.tool_id,
    ).where(Connection.id == scope.connection_id, Connection.agent_id == scope.agent_id,
            Connection.active.is_(True), indexing_mode_expression().in_(("known_uris", "recursive"))))
    return stamp == scope.stamp


async def project_entry(entry: FileCatalogEntry) -> None:
    descriptor = ResourceDescriptor.model_validate(entry.descriptor)
    # Explicit fields only: providers' arbitrary metadata may carry secrets.
    description = json.dumps({
        "uri": entry.uri, "name": descriptor.name, "media_type": descriptor.media_type,
        "size": descriptor.size, "modified_at": descriptor.modified_at,
        "revision": descriptor.revision, "checksum": descriptor.checksum, "etag": descriptor.etag,
    }, ensure_ascii=False)
    entry.memory_item_id = await project_catalogue_entry(
        identity=entry.id, agent_id=entry.agent_id, item_id=entry.memory_item_id,
        title=descriptor.name or entry.uri, uri=entry.uri, directory=descriptor.is_collection,
        description=description, notes="\n\n".join(part for part in (entry.notes, entry.enrichment_text) if part),
    )


async def observe_descriptors(scope: ObservationScope, descriptors: list[ResourceDescriptor]) -> None:
    db = get_db()
    await lock_binding(scope)
    if not await current_binding(scope):
        raise PermissionError("Source binding changed during the file operation")
    for descriptor in descriptors:
        uri = str(parse_resource_uri(descriptor.uri, allow_empty=True))
        key = hashlib.sha256(uri.encode()).hexdigest()
        stale = await db.scalar(select(FileCatalogEntry.id).where(
            FileCatalogEntry.connection_id == scope.connection_id,
            FileCatalogEntry.binding_stamp == scope.stamp, FileCatalogEntry.runtime == scope.runtime,
            FileCatalogEntry.present.is_(False), FileCatalogEntry.operation_started_at > scope.started_at,
            or_(FileCatalogEntry.uri == uri, func.starts_with(uri, func.rtrim(FileCatalogEntry.uri, "/") + "/")),
        ).limit(1))
        if stale is not None:
            continue
        entry = await db.scalar(select(FileCatalogEntry).where(
            FileCatalogEntry.connection_id == scope.connection_id,
            FileCatalogEntry.binding_stamp == scope.stamp,
            FileCatalogEntry.runtime == scope.runtime, FileCatalogEntry.uri_key == key,
        ))
        if entry is not None and entry.operation_started_at > scope.started_at:
            continue
        generation = 1
        if entry is not None and not entry.present:
            generation = entry.generation + 1
            # A proven deletion ends the identity. A later occupant of that name
            # does not inherit the previous file's notes or Memory projection.
            entry.uri_key = hashlib.sha256(f"retained:{entry.id}".encode()).hexdigest()
            await db.flush()
            entry = None
        if entry is None:
            entry = FileCatalogEntry(
                agent_id=scope.agent_id, connection_id=scope.connection_id,
                binding_stamp=scope.stamp, runtime=scope.runtime, uri=uri, uri_key=key,
                operation_started_at=scope.started_at, last_seen_at=scope.started_at,
                descriptor={}, notes="", present=True, generation=generation,
            )
            db.add(entry)
            await db.flush()
        entry.present = True
        entry.operation_started_at = scope.started_at
        entry.last_seen_at = datetime.now(timezone.utc)
        entry.descriptor = descriptor.model_dump(exclude={"metadata", "capabilities", "indexing_status"})
        entry.source_version = descriptor_version(entry.descriptor)
        if entry.enrichment_version != entry.source_version:
            entry.enrichment_text = ""
        await project_entry(entry)
    await db.flush()


async def observe_deletion(scope: ObservationScope, uri: str) -> None:
    db = get_db()
    await lock_binding(scope)
    if not await current_binding(scope):
        raise PermissionError("Source binding changed during the file operation")
    canonical = str(parse_resource_uri(uri, allow_empty=True))
    # The facade's successful delete is proof for this path and its descendants.
    entries = await db.scalars(select(FileCatalogEntry).where(
        FileCatalogEntry.connection_id == scope.connection_id,
        FileCatalogEntry.binding_stamp == scope.stamp, FileCatalogEntry.runtime == scope.runtime,
        or_(FileCatalogEntry.uri == canonical, FileCatalogEntry.uri.startswith(canonical.rstrip("/") + "/", autoescape=True)),
    ))
    known = False
    for entry in entries:
        known = known or entry.uri == canonical
        if entry.operation_started_at <= scope.started_at:
            entry.present = False
            entry.operation_started_at = scope.started_at
    if not known:
        db.add(FileCatalogEntry(
            agent_id=scope.agent_id, connection_id=scope.connection_id, binding_stamp=scope.stamp,
            runtime=scope.runtime, uri=canonical, uri_key=hashlib.sha256(canonical.encode()).hexdigest(),
            descriptor={}, notes="", present=False, operation_started_at=scope.started_at,
            last_seen_at=scope.started_at,
        ))
    await db.flush()


async def observe_membership(scope: ObservationScope, parent_uri: str, child_uris: list[str]) -> None:
    entries = list(await get_db().scalars(select(FileCatalogEntry).where(
        FileCatalogEntry.connection_id == scope.connection_id,
        FileCatalogEntry.binding_stamp == scope.stamp, FileCatalogEntry.runtime == scope.runtime,
        FileCatalogEntry.present.is_(True), FileCatalogEntry.uri.in_([parent_uri, *child_uris]),
    )))
    parent = next((entry for entry in entries if entry.uri == parent_uri), None)
    if parent is not None and parent.memory_item_id is not None:
        await link_catalogue_entries(parent.memory_item_id, [entry.memory_item_id for entry in entries
            if entry.uri in child_uris and entry.memory_item_id is not None], agent_id=scope.agent_id)


async def observe_move(scope: ObservationScope, source_uri: str, destination: ResourceDescriptor) -> None:
    """Preserve identity/notes for a proven rename inside the same binding.

    An overwrite keeps both retained identities; its destination projection is
    refreshed through the ordinary observation path instead of merging notes.
    """
    db = get_db()
    await lock_binding(scope)
    if not await current_binding(scope):
        raise PermissionError("Source binding changed during the file operation")
    source = await db.scalar(select(FileCatalogEntry).where(
        FileCatalogEntry.connection_id == scope.connection_id,
        FileCatalogEntry.binding_stamp == scope.stamp, FileCatalogEntry.runtime == scope.runtime,
        FileCatalogEntry.uri_key.in_((hashlib.sha256(source_uri.encode()).hexdigest(),
                                     hashlib.sha256((source_uri.rstrip("/") + "/").encode()).hexdigest())),
    ))
    target = await db.scalar(select(FileCatalogEntry).where(
        FileCatalogEntry.connection_id == scope.connection_id,
        FileCatalogEntry.binding_stamp == scope.stamp, FileCatalogEntry.runtime == scope.runtime,
        FileCatalogEntry.uri_key == hashlib.sha256(destination.uri.encode()).hexdigest(),
    ))
    if source is None or target is not None or source.operation_started_at > scope.started_at:
        await observe_deletion(scope, source_uri)
        return
    if source.memory_item_id is not None:
        await detach_catalogue_parent_links(source.memory_item_id)
    descendants = list(await db.scalars(select(FileCatalogEntry).where(
        FileCatalogEntry.connection_id == scope.connection_id,
        FileCatalogEntry.binding_stamp == scope.stamp, FileCatalogEntry.runtime == scope.runtime,
        FileCatalogEntry.id != source.id,
        FileCatalogEntry.present.is_(True), FileCatalogEntry.uri.startswith(source_uri.rstrip("/") + "/", autoescape=True),
    ))) if destination.is_collection else []
    for moving in [source, *descendants]:
        old_uri, old_key = moving.uri, moving.uri_key
        moving.uri = destination.uri if moving is source else destination.uri.rstrip("/") + "/" + old_uri[len(source_uri.rstrip("/") + "/"):]
        moving.uri_key = hashlib.sha256(moving.uri.encode()).hexdigest()
        moving.operation_started_at = scope.started_at
        moving.descriptor = {**moving.descriptor, "uri": moving.uri}
        # Reserve the former name with a tombstone before a late response arrives.
        await db.flush()
        db.add(FileCatalogEntry(
            agent_id=scope.agent_id, connection_id=scope.connection_id,
            binding_stamp=scope.stamp, runtime=scope.runtime, uri=old_uri, uri_key=old_key,
            descriptor=moving.descriptor, notes="", present=False,
            operation_started_at=scope.started_at, last_seen_at=scope.started_at,
        ))
        if moving is not source:
            await project_entry(moving)
    await db.flush()


async def catalogue_source_readable(item_id: UUID, agent_id: int) -> bool:
    db = get_db()
    entry = await db.scalar(select(FileCatalogEntry).join(
        Connection, Connection.id == FileCatalogEntry.connection_id,
    ).join(ToolModel, ToolModel.id == Connection.tool_id).where(
        FileCatalogEntry.memory_item_id == item_id, FileCatalogEntry.agent_id == agent_id,
        FileCatalogEntry.present.is_(True), _live_binding(),
    ))
    if entry is None:
        return False
    from .resource_service import resource_info
    from .resource_observation import suspend_observations
    try:
        with suspend_observations():
            ctx = ResourceContext(agent_id=agent_id, runtime=entry.runtime)
            scope = await observation_scope(ctx, entry.uri)
            if scope is None or scope.connection_id != entry.connection_id or scope.stamp != entry.binding_stamp:
                return False
            await resource_info(ctx, entry.uri)
    except Exception:
        return False
    return True


async def annotate_catalogue_entry(ctx: ResourceContext, uri: object, notes: str) -> UUID:
    if len(notes) > 50_000:
        raise ValueError("Resource notes exceed 50000 characters")
    scope = await observation_scope(ctx, uri)
    if scope is None:
        raise PermissionError("This resource is excluded from indexing")
    from .resource_service import resource_info
    from .resource_observation import suspend_observations
    with suspend_observations():
        descriptor = await resource_info(ctx, uri)
    db = get_db()
    async with catalogue_projection_write():
        async with db.begin_nested():
            await observe_descriptors(scope, [descriptor])
            entry = await db.scalar(select(FileCatalogEntry).where(
                FileCatalogEntry.connection_id == scope.connection_id, FileCatalogEntry.binding_stamp == scope.stamp,
                FileCatalogEntry.runtime == scope.runtime, FileCatalogEntry.uri_key == hashlib.sha256(descriptor.uri.encode()).hexdigest(),
            ))
            if entry is None or not await current_binding(scope):
                raise PermissionError("Resource binding changed")
            entry.notes = notes
            await project_entry(entry)
            assert entry.memory_item_id is not None
            item_id = entry.memory_item_id
        await db.commit()
    return item_id
