"""Opaque binary resource providers, independent of application domains."""

from typing import Protocol, runtime_checkable

class ResourceStorageError(RuntimeError):
    """Base error raised by a resource-storage provider."""


class ResourceNotFoundError(ResourceStorageError):
    """The opaque resource identifier does not exist in its provider."""


class ResourceTooLargeError(ResourceStorageError):
    """The resource exceeds the configured provider limit."""


@runtime_checkable
class ResourceStorage(Protocol):
    """Small provider-neutral CRUD contract for opaque binary resources."""

    @property
    def code(self) -> str: ...

    async def create(self, content: bytes) -> str: ...

    async def read(self, resource_id: str) -> bytes: ...

    async def update(self, resource_id: str, content: bytes) -> None: ...

    async def delete(self, resource_id: str) -> bool: ...
