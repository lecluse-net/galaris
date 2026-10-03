"""Observe completed public operations, without replaying an external mutation."""

from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import ParamSpec, TypeVar

from loguru import logger
from pydantic import BaseModel

from core.database import get_db
from app.memory import catalogue_projection_write

from .catalogue import ObservationScope, observation_scope, observe_deletion, observe_descriptors, observe_move, observe_membership, lock_observation_scopes
from .resource_contracts import (
    ResourceContext, ResourceDescriptor, ResourceListing, ResourceMutation,
    ResourceRead, ResourceSearchResult, ResourceTransfer,
)
from .resource_uri import parse_resource_uri
from .models import FileObservationRepair
from datetime import datetime, timezone

P = ParamSpec("P")
T = TypeVar("T")
_suspended: ContextVar[bool] = ContextVar("file_catalogue_suspended", default=False)


@contextmanager
def suspend_observations() -> Generator[None]:
    token = _suspended.set(True)
    try:
        yield
    finally:
        _suspended.reset(token)


async def observe_received_resources(connection_id: int, descriptors: list[ResourceDescriptor]) -> None:
    """Journal admission observes attachment metadata without downloading bytes."""
    from sqlalchemy import select
    from app.connection import Connection
    from app.tools import ToolModel
    from .catalogue import binding_stamp, indexing_mode_expression
    db = get_db()
    row = (await db.execute(select(Connection.agent_id, binding_stamp(), indexing_mode_expression()).join(
        ToolModel, ToolModel.id == Connection.tool_id,
    ).where(Connection.id == connection_id, Connection.active.is_(True)))).one_or_none()
    if row is None or row[2] == "excluded":
        return
    scope = ObservationScope(connection_id, int(row[0]), str(row[1]), "internal", datetime.now(timezone.utc))
    repairs: list[FileObservationRepair] = []
    for descriptor in descriptors:
        repairs.extend(await stage_repairs({parse_resource_uri(descriptor.uri).scheme: scope}, descriptor, recursive=False))
    # The Messenger journal owns commit. Keep its metadata repair durable even
    # when the immediate projection fails, without rejecting an incoming message.
    try:
        async with catalogue_projection_write():
            async with db.begin_nested():
                await observe_descriptors(scope, descriptors)
                for repair in repairs:
                    repair.status = "success"
    except Exception as error:
        logger.warning("Attachment metadata retained for catalogue repair: {}", type(error).__name__)


def observe_operation(function: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    @wraps(function)
    async def observed(*args: P.args, **kwargs: P.kwargs) -> T:
        if _suspended.get():
            return await function(*args, **kwargs)
        try:
            db = get_db()
        except RuntimeError:
            return await function(*args, **kwargs)
        ctx = args[0] if args else kwargs.get("ctx")
        if not isinstance(ctx, ResourceContext):
            return await function(*args, **kwargs)
        source = args[1] if len(args) > 1 else kwargs.get("uri", kwargs.get("source", kwargs.get("path")))
        destination = args[2] if len(args) > 2 else kwargs.get("destination")
        scopes: dict[str, ObservationScope] = {}
        failed = False
        with suspend_observations():
            for uri in [source, destination] if function.__name__ in {"resource_copy", "resource_move"} else [source]:
                if uri is None:
                    continue
                try:
                    async with db.begin_nested():
                        scope = await observation_scope(ctx, uri)
                    if scope is not None:
                        scopes[parse_resource_uri(uri, allow_empty=True).scheme] = scope
                except Exception as error:
                    failed = True
                    # No URI, content or credentials in diagnostic output.
                    logger.warning("File catalogue preparation failed: {}", type(error).__name__)
            result = await function(*args, **kwargs)
            if scopes:
                repairs: list[FileObservationRepair] = []
                try:
                    repairs = await stage_repairs(scopes, result, recursive=bool(kwargs.get("recursive", False)))
                    await db.commit()
                    async with catalogue_projection_write():
                        async with db.begin_nested():
                            await lock_observation_scopes(list(scopes.values()))
                            await observe_result(ctx, scopes, result, recursive=bool(kwargs.get("recursive", False)))
                            for repair in repairs:
                                repair.status = "success"
                        await db.commit()
                except Exception as error:
                    await db.rollback()
                    failed = True
                    logger.warning("File operation succeeded; catalogue update failed: {}", type(error).__name__)
        if isinstance(result, BaseModel) and "indexing_status" in type(result).model_fields:
            result = result.model_copy(update={"indexing_status": "failed" if failed else "indexed" if scopes else "excluded"})
        return result
    return observed


async def stage_repairs(scopes: dict[str, ObservationScope], result: object, *, recursive: bool) -> list[FileObservationRepair]:
    """Journal only metadata and proven operations, never file bytes or search excerpts."""
    if isinstance(result, ResourceRead):
        safe: BaseModel = ResourceMutation(uri=result.uri, operation="write", state="observed")
    elif isinstance(result, ResourceSearchResult):
        safe = ResourceListing(uri=result.uri, entries=[hit.resource.model_copy(update={"metadata": {}}) for hit in result.hits], truncated=True)
        recursive = True  # Search matches do not prove parent membership.
    elif isinstance(result, ResourceListing):
        safe = result.model_copy(update={"entries": [entry.model_copy(update={"metadata": {}}) for entry in result.entries]})
    elif isinstance(result, ResourceDescriptor):
        safe = result.model_copy(update={"metadata": {}})
    elif isinstance(result, (ResourceMutation, ResourceTransfer)):
        safe = result
    else:
        return []
    repairs: list[FileObservationRepair] = []
    for scope in scopes.values():
        repair = FileObservationRepair(agent_id=scope.agent_id, connection_id=scope.connection_id,
            binding_stamp=scope.stamp, runtime=scope.runtime, started_at=scope.started_at,
            next_attempt_at=datetime.now(timezone.utc), payload={"kind": type(safe).__name__,
                "result": safe.model_dump(mode="json"), "recursive": recursive})
        get_db().add(repair)
        repairs.append(repair)
    await get_db().flush()
    return repairs


async def observe_result(ctx: ResourceContext, scopes: dict[str, ObservationScope], result: object, *, recursive: bool = False) -> None:
    from .resource_service import resource_info
    descriptors: list[ResourceDescriptor] = []
    if isinstance(result, ResourceDescriptor):
        descriptors = [result]
    elif isinstance(result, ResourceListing):
        descriptors = [ResourceDescriptor(uri=result.uri, name=parse_resource_uri(result.uri, allow_empty=True).decoded_locator or "/", is_collection=True, media_type="inode/directory"), *result.entries]
    elif isinstance(result, ResourceSearchResult):
        descriptors = [hit.resource for hit in result.hits]
    elif isinstance(result, ResourceMutation) and result.operation == "delete":
        scope = scopes.get(parse_resource_uri(result.uri).scheme)
        if scope is not None:
            await observe_deletion(scope, result.uri)
        return
    elif isinstance(result, (ResourceRead, ResourceMutation, ResourceTransfer)):
        descriptors = [await resource_info(ctx, result.uri)]
        if isinstance(result, ResourceTransfer) and not result.moved:
            descriptors.append(await resource_info(ctx, result.source_uri))
        if isinstance(result, ResourceTransfer) and result.moved:
            scope = scopes.get(parse_resource_uri(result.source_uri).scheme)
            if scope is not None:
                if parse_resource_uri(result.uri).scheme == parse_resource_uri(result.source_uri).scheme:
                    await observe_move(scope, result.source_uri, descriptors[0])
                else:
                    await observe_deletion(scope, result.source_uri)
    for scheme, scope in scopes.items():
        await observe_descriptors(scope, [descriptor for descriptor in descriptors
                                       if parse_resource_uri(descriptor.uri, allow_empty=True).scheme == scheme])
        if isinstance(result, ResourceListing) and not recursive:
            await observe_membership(scope, result.uri, [descriptor.uri for descriptor in result.entries
                                                        if parse_resource_uri(descriptor.uri, allow_empty=True).scheme == scheme])
