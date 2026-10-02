"""Durable file discovery and projection repair, one bounded page per turn."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, delete, or_, func, exists, update

from app.connection import Connection
from app.tools import ToolModel
from app.memory import catalogue_projection_write
from core.database import get_db

from .catalogue import ObservationScope, current_binding, lock_binding, observation_scope, observe_descriptors, observe_deletion, observe_membership, indexing_mode_expression, binding_stamp
from .models import FileCatalogEntry, FileIndexRun, FileObservationRepair
from .resource_contracts import ResourceContext
from .resource_observation import suspend_observations
from .resource_uri import parse_resource_uri
from .indexing_contracts import FileIndexProgress, FileIndexPage


def now() -> datetime:
    return datetime.now(timezone.utc)


async def index_progress(agent_id: int, page: int, page_size: int) -> FileIndexPage:
    db = get_db()
    runs = await db.scalars(select(FileIndexRun).where(FileIndexRun.agent_id == agent_id)
        .order_by(FileIndexRun.updated_at.desc(), FileIndexRun.id).offset((page - 1) * page_size).limit(page_size))
    total = int(await db.scalar(select(func.count()).select_from(FileIndexRun).where(FileIndexRun.agent_id == agent_id)) or 0)
    counts: dict[str, int] = {str(row[0]): int(row[1]) for row in (await db.execute(select(FileObservationRepair.status, func.count()).where(
        FileObservationRepair.agent_id == agent_id).group_by(FileObservationRepair.status))).all()}
    return FileIndexPage(runs=[FileIndexProgress.model_validate(run) for run in runs], total=total,
        pending_repairs=counts.get("pending", 0), failed_repairs=counts.get("error", 0))


async def retry_repairs(agent_id: int) -> int:
    ids = (await get_db().scalars(update(FileObservationRepair).where(FileObservationRepair.agent_id == agent_id,
        FileObservationRepair.status == "error").values(status="pending", attempts=0,
        next_attempt_at=now(), error_type=None).returning(FileObservationRepair.id))).all()
    await get_db().commit()
    return len(ids)


async def start_index_run(ctx: ResourceContext, root: str, *, max_entries: int = 100000, max_depth: int = 64) -> FileIndexRun:
    if not 1 <= max_entries <= 1000000 or not 0 <= max_depth <= 64:
        raise ValueError("Invalid file indexing budget")
    root = str(parse_resource_uri(root, allow_empty=True))
    if len(root) > 8192:
        raise ValueError("File indexing root exceeds its size limit")
    scope = await observation_scope(ctx, root)
    if scope is None:
        raise PermissionError("This source is excluded from file indexing")
    mode = await get_db().scalar(select(indexing_mode_expression()).select_from(Connection).join(
        ToolModel, ToolModel.id == Connection.tool_id).where(Connection.id == scope.connection_id))
    if mode != "recursive":
        raise PermissionError("This source does not support automatic traversal")
    await lock_binding(scope)
    existing = await get_db().scalar(select(FileIndexRun).where(
        FileIndexRun.connection_id == scope.connection_id, FileIndexRun.binding_stamp == scope.stamp,
        FileIndexRun.runtime == scope.runtime, FileIndexRun.root_uri == root,
        FileIndexRun.status.in_(("queued", "running", "retry")),
    ))
    if existing is not None:
        return existing
    run = FileIndexRun(agent_id=ctx.agent_id, connection_id=scope.connection_id,
        binding_stamp=scope.stamp, runtime=scope.runtime, root_uri=root,
        frontier=[{"uri": root, "cursor": None, "depth": 0}], started_at=now(),
        updated_at=now(), next_attempt_at=now(), max_entries=max_entries, max_depth=max_depth)
    get_db().add(run)
    await get_db().flush()
    return run


async def cancel_index_run(run_id: UUID, agent_id: int) -> bool:
    run = await get_db().scalar(select(FileIndexRun).where(FileIndexRun.id == run_id,
        FileIndexRun.agent_id == agent_id).with_for_update())
    if run is None:
        return False
    if run.status in {"queued", "running", "retry"}:
        run.status = "cancelled"
        run.updated_at = now()
    return True


async def _reconcile_directory(scope: ObservationScope, uri: str, before: datetime) -> None:
    prefix = uri if uri.endswith("://") else uri.rstrip("/") + "/"
    entries = await get_db().scalars(select(FileCatalogEntry).where(
        FileCatalogEntry.connection_id == scope.connection_id, FileCatalogEntry.binding_stamp == scope.stamp,
        FileCatalogEntry.runtime == scope.runtime, FileCatalogEntry.present.is_(True),
        FileCatalogEntry.last_seen_at < before, FileCatalogEntry.operation_started_at < before,
        FileCatalogEntry.uri.startswith(prefix, autoescape=True),
    ))
    # A complete direct listing proves absence only for direct children.
    for entry in list(entries):
        if "/" not in entry.uri[len(prefix):].rstrip("/"):
            await observe_deletion(ObservationScope(scope.connection_id, scope.agent_id,
                scope.stamp, scope.runtime, before), entry.uri)


async def process_index_page(run: FileIndexRun) -> None:
    from .resource_service import resource_info, resource_list
    ctx = ResourceContext(agent_id=run.agent_id, runtime=run.runtime)
    scope = await observation_scope(ctx, run.root_uri)
    if scope is None or scope.stamp != run.binding_stamp or scope.connection_id != run.connection_id:
        run.status = "excluded"
        return
    mode = await get_db().scalar(select(indexing_mode_expression()).select_from(Connection).join(ToolModel, ToolModel.id == Connection.tool_id).where(Connection.id == scope.connection_id))
    if mode != "recursive":
        run.status = "excluded"
        return
    frontier = [dict(frame) for frame in run.frontier]
    if not frontier:
        run.status = "success"
        return
    frame = frontier[0]
    uri, cursor, depth = str(frame["uri"]), frame.get("cursor"), int(frame["depth"])
    budget = min(500, run.max_entries - run.scanned)
    if budget <= 0:
        run.status = "partial"
        return
    with suspend_observations():
        parent = await resource_info(ctx, uri)
        listing = await resource_list(ctx, uri, recursive=False, max_entries=budget,
            cursor=str(cursor) if cursor else None)
    if listing.next_cursor and len(listing.next_cursor) > 65536:
        raise ValueError("Provider cursor exceeds its size limit")
    # Never accept provider escapes, repeated cursors, or unpageable truncation as complete.
    prefix = uri if uri.endswith("://") else uri.rstrip("/") + "/"
    for entry in listing.entries:
        if not entry.uri.startswith(prefix) or "/" in entry.uri[len(prefix):].rstrip("/"):
            raise ValueError("Provider returned a resource outside the direct collection")
        child_scope = await observation_scope(ctx, entry.uri)
        if child_scope is None or child_scope.stamp != scope.stamp:
            raise PermissionError("Provider listing contains an excluded resource")
    await observe_descriptors(scope, [parent, *listing.entries])
    await observe_membership(scope, parent.uri, [entry.uri for entry in listing.entries])
    if run.error_type not in {"DepthLimit", "FrontierLimit"}:
        run.error_type = None
    run.scanned += len(listing.entries)
    for entry in listing.entries:
        if entry.is_collection:
            if depth >= run.max_depth:
                run.error_type = "DepthLimit"
            elif not any(child["uri"] == entry.uri for child in frontier):
                if len(frontier) >= 4096 or len(entry.uri) > 8192:
                    run.error_type = "FrontierLimit"
                else:
                    frontier.append({"uri": entry.uri, "cursor": None, "depth": depth + 1})
    if listing.truncated:
        if not listing.next_cursor:
            run.status = "partial"
            run.error_type = "UnpageableListing"
            return
        if listing.next_cursor == cursor:
            raise ValueError("Provider cursor did not advance")
        frame["cursor"] = listing.next_cursor
    else:
        await _reconcile_directory(scope, uri, run.started_at)
        frontier.pop(0)
        run.directories += 1
    run.frontier = frontier
    run.status = "running" if frontier else "partial" if run.error_type in {"DepthLimit", "FrontierLimit"} else "success"
    run.attempts = 0
    run.updated_at = now()
    run.next_attempt_at = now()


async def schedule_automatic_runs() -> None:
    recent = exists(select(FileIndexRun.id).where(
        FileIndexRun.connection_id == Connection.id, FileIndexRun.binding_stamp == binding_stamp(),
        FileIndexRun.runtime == "internal", FileIndexRun.root_uri == ToolModel.code + "://",
        or_(FileIndexRun.status.in_(("queued", "running", "retry")), FileIndexRun.updated_at > now() - timedelta(hours=6)),
    ).correlate(Connection, ToolModel))
    rows = (await get_db().execute(select(Connection.agent_id, ToolModel.code).join(
        ToolModel, ToolModel.id == Connection.tool_id).where(Connection.active.is_(True),
        indexing_mode_expression() == "recursive", ~recent).order_by(Connection.id).limit(20))).all()
    for agent_id, code in rows:
        root = f"{code}://"
        try:
            async with get_db().begin_nested():
                await start_index_run(ResourceContext(agent_id=agent_id, runtime="internal"), root)
        except (PermissionError, ValueError):
            continue


async def indexing_tick() -> None:
    """Scheduler callback: isolated session is supplied by the scheduler."""
    db = get_db()
    await schedule_automatic_runs()
    await db.commit()
    run = await db.scalar(select(FileIndexRun).where(FileIndexRun.status.in_(("queued", "running", "retry")),
        FileIndexRun.next_attempt_at <= now()).order_by(FileIndexRun.updated_at, FileIndexRun.id)
        .limit(1).with_for_update(skip_locked=True))
    if run is None:
        return
    try:
        async with catalogue_projection_write():
            async with db.begin_nested():
                await process_index_page(run)
    except Exception as error:
        await db.refresh(run)
        run.attempts += 1
        run.error_type = type(error).__name__
        run.status = "error" if run.attempts >= 5 else "retry"
        run.updated_at = now()
        run.next_attempt_at = now() + timedelta(seconds=min(3600, 30 * 2 ** run.attempts))
        # A revision conflict invalidates the old cursor, never the source.
        if type(error).__name__ == "ResourceRevisionConflict" and run.frontier:
            run.frontier = [{**run.frontier[0], "cursor": None}, *run.frontier[1:]]
    await db.commit()


async def repair_tick() -> None:
    from .resource_observation import observe_result
    from .resource_contracts import ResourceDescriptor, ResourceListing, ResourceMutation, ResourceTransfer
    db = get_db()
    repair = await db.scalar(select(FileObservationRepair).where(
        FileObservationRepair.status == "pending", FileObservationRepair.next_attempt_at <= now(),
    ).order_by(FileObservationRepair.next_attempt_at).limit(1))
    if repair is None:
        return
    if repair.connection_id is None:
        repair.status = "excluded"
        await db.commit()
        return
    scope = ObservationScope(repair.connection_id, repair.agent_id, repair.binding_stamp,
        repair.runtime, repair.started_at)
    await lock_binding(scope)
    repair = await db.scalar(select(FileObservationRepair).where(FileObservationRepair.id == repair.id,
        FileObservationRepair.status == "pending").with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if repair is None:
        return
    if not await current_binding(scope):
        repair.status = "excluded"
        await db.commit()
        return
    models = {model.__name__: model for model in (ResourceDescriptor, ResourceListing, ResourceMutation, ResourceTransfer)}
    try:
        result = models[str(repair.payload["kind"])].model_validate(repair.payload["result"])
        ctx = ResourceContext(agent_id=repair.agent_id, runtime=repair.runtime)
        with suspend_observations():
            async with catalogue_projection_write():
                async with db.begin_nested():
                    scheme = await db.scalar(select(ToolModel.code).join(Connection).where(Connection.id == repair.connection_id))
                    if scheme is None:
                        raise PermissionError("Source connection disappeared")
                    await observe_result(ctx, {scheme: scope},
                        result, recursive=bool(repair.payload["recursive"]))
        repair.status = "success"
    except Exception as error:
        repair.attempts += 1
        repair.error_type = type(error).__name__
        repair.status = "error" if repair.attempts >= 5 else "pending"
        repair.next_attempt_at = now() + timedelta(seconds=min(3600, 30 * 2 ** repair.attempts))
    await db.commit()


async def prune_index_history() -> None:
    """Retain diagnostics for 30 days without retaining file contents."""
    cutoff = now() - timedelta(days=30)
    await get_db().execute(delete(FileObservationRepair).where(FileObservationRepair.status != "pending", FileObservationRepair.started_at < cutoff))
    await get_db().execute(delete(FileIndexRun).where(FileIndexRun.status.not_in(("queued", "running", "retry")), FileIndexRun.updated_at < cutoff))
    await get_db().commit()


async def refresh_known_tick() -> None:
    """Validate one known URI without traversing providers configured for known URIs."""
    from .resource_service import resource_info
    db = get_db()
    entry = await db.scalar(select(FileCatalogEntry).join(Connection).join(ToolModel).where(
        FileCatalogEntry.present.is_(True), Connection.active.is_(True),
        indexing_mode_expression().in_(("known_uris", "recursive")),
        or_(FileCatalogEntry.checked_at.is_(None), FileCatalogEntry.checked_at < now() - timedelta(hours=6)),
    ).order_by(func.coalesce(FileCatalogEntry.checked_at, FileCatalogEntry.last_seen_at))
        .limit(1))
    if entry is None:
        return
    ctx = ResourceContext(agent_id=entry.agent_id, runtime=entry.runtime)
    scope = await observation_scope(ctx, entry.uri)
    if scope is None or scope.stamp != entry.binding_stamp:
        entry.checked_at = now()
        await db.commit()
        return
    try:
        with suspend_observations():
            async with catalogue_projection_write():
                async with db.begin_nested():
                    descriptor = await resource_info(ctx, entry.uri)
                    await observe_descriptors(scope, [descriptor])
    except FileNotFoundError:
        await observe_deletion(scope, entry.uri)
    except Exception:
        # An unavailable or forbidden source provides no deletion proof.
        pass
    entry.checked_at = now()
    await db.commit()
