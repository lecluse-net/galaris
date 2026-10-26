"""Native domain provider ports, bound by the application composition root."""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .resource_contracts import (MaterializedResource, ResourceContext, ResourceDescriptor,
    ResourceListing, ResourceMutation, ResourceRead, ResourceSchemeDescription, ResourceSearchResult)
from .resource_uri import ResourceUri


class NativeResourceProvider(Protocol):
    def description(self) -> ResourceSchemeDescription: ...
    async def info(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceDescriptor: ...
    async def list(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceListing: ...
    async def read(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceRead: ...
    async def create(self, ctx: ResourceContext, uri: ResourceUri, content: bytes, **options: Any) -> ResourceMutation: ...
    async def write(self, ctx: ResourceContext, uri: ResourceUri, content: bytes, **options: Any) -> ResourceMutation: ...
    async def append(self, ctx: ResourceContext, uri: ResourceUri, content: str, **options: Any) -> ResourceMutation: ...
    async def edit(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceMutation: ...
    async def delete(self, ctx: ResourceContext, uri: ResourceUri, **options: Any) -> ResourceMutation: ...
    async def search(self, ctx: ResourceContext, uri: ResourceUri, query: str, **options: Any) -> ResourceSearchResult: ...
    async def materialize(self, ctx: ResourceContext, uri: ResourceUri, destination: Path, **options: Any) -> MaterializedResource: ...


@runtime_checkable
class NativeResourceRenamer(Protocol):
    """Optional metadata mutation; content providers need not support renaming."""

    async def rename(self, ctx: ResourceContext, uri: ResourceUri, name: str,
                     *, expected_lock_version: int) -> ResourceMutation: ...


_providers: dict[str, NativeResourceProvider] = {}
_aliases: dict[str, Callable[[ResourceContext, ResourceUri], Awaitable[ResourceUri]]] = {}


def register_native_provider(scheme: str, provider: NativeResourceProvider) -> None:
    _providers[scheme] = provider


def native_provider(scheme: str) -> NativeResourceProvider | None:
    return _providers.get(scheme)


def native_descriptions() -> list[ResourceSchemeDescription]:
    return [provider.description() for _, provider in sorted(_providers.items())]


def register_resource_aliases(key: str, resolver: Callable[[ResourceContext, ResourceUri], Awaitable[ResourceUri]]) -> None:
    _aliases[key] = resolver


async def resolve_native_alias(ctx: ResourceContext, reference: ResourceUri) -> ResourceUri:
    for resolver in _aliases.values():
        reference = await resolver(ctx, reference)
    return reference
