"""Translate Document-owned folder projections to generic file descriptors."""

from uuid import UUID
import json
from typing import Literal, cast

from app.document.facade import describe_folder_resource, list_folder_resources, read_folder_tree
from core.user import HumanActor

from .resource_contracts import ResourceContext, ResourceDescriptor, ResourceListing, ResourceRead
from .resource_uri import ResourceUri


def is_document_folder(uri: ResourceUri) -> bool:
    return uri.scheme == "document" and uri.segments[:1] == ("folders",)


def _identity(uri: ResourceUri) -> UUID | None:
    return UUID(uri.segments[1]) if len(uri.segments) == 2 else None


def _actor(ctx: ResourceContext) -> int | HumanActor:
    return HumanActor(ctx.management_scope.user_id) if ctx.management_scope else ctx.agent_id


async def folder_info(ctx: ResourceContext, uri: ResourceUri) -> ResourceDescriptor:
    descriptor = ResourceDescriptor.model_validate(await describe_folder_resource(_identity(uri), _actor(ctx)))
    if uri.segments == ("folders",):
        descriptor.label_code = "collection_document_folders"
    return descriptor


async def folder_list(ctx: ResourceContext, uri: ResourceUri, *, limit: int, cursor: str | None,
    query: str = "", navigation: bool = False) -> ResourceListing:
    listing = await list_folder_resources(_identity(uri), _actor(ctx),
        limit=limit, offset=int(cursor or "0"), query=query, navigation=navigation)
    listing["uri"] = str(uri)
    result = ResourceListing.model_validate(listing)
    for entry in [*result.entries, *result.ancestors]:
        if entry.uri == "document://":
            entry.label_code = "scheme_document"
        elif entry.uri == "document://folders/":
            entry.label_code = "collection_document_folders"
    return result


class FolderTreeRead(ResourceRead):
    """Complete JSON pages bounded by placement count instead of text characters."""

    offset_unit: Literal["item"] = "item"
    page_size: Literal[200] = 200


async def folder_read(ctx: ResourceContext, uri: ResourceUri, *, offset: int) -> ResourceRead:
    identity = _identity(uri)
    if identity is None:
        raise IsADirectoryError("Choose an exact document://folders/<uuid>/ URI from file_list")
    tree = await read_folder_tree(identity, _actor(ctx), offset=offset)
    page = cast(dict[str, int | None], tree["pagination"])
    return FolderTreeRead(uri=str(uri), content=json.dumps(tree, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json", start=cast(int, page["offset"]),
        end=cast(int, page["offset"]) + cast(int, page["returned"]), total=cast(int, page["total"]),
        next_offset=page["next_offset"])
