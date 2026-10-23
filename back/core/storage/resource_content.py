"""Row-owned text providers; each domain registers its own lookup and references."""

from collections.abc import Awaitable, Callable, Collection
from uuid import uuid4

from .resource_contracts import ResourceStorageError

InlineReader = Callable[[str], Awaitable[bytes | None]]
ReferenceChecker = Callable[[str, str], Awaitable[bool]]
BatchReferenceChecker = Callable[[str, Collection[str]], Awaitable[set[str]]]
_readers: dict[str, InlineReader] = {}
_references: dict[str, ReferenceChecker] = {}
_batch_references: dict[str, BatchReferenceChecker] = {}


def register_resource_content(
    domain: str, reader: InlineReader, referenced: ReferenceChecker,
    *, referenced_batch: BatchReferenceChecker | None = None,
) -> None:
    """Composition supplies storage knowledge without moving domain ACLs to Core."""
    _readers[domain] = reader
    _references[domain] = referenced
    if referenced_batch is not None:
        _batch_references[domain] = referenced_batch
    else:
        _batch_references.pop(domain, None)


async def read_inline_content(resource_ref: str) -> bytes | None:
    for reader in tuple(_readers.values()):
        if (content := await reader(resource_ref)) is not None:
            return content
    return None


async def resource_is_referenced(provider_code: str, resource_ref: str) -> bool:
    for checker in tuple(_references.values()):
        if await checker(provider_code, resource_ref):
            return True
    return False


async def referenced_resources(provider_code: str, resource_refs: Collection[str]) -> set[str]:
    if not resource_refs:
        return set()
    referenced: set[str] = set()
    for domain, checker in tuple(_references.items()):
        pending = set(resource_refs) - referenced
        if not pending:
            break
        if batch := _batch_references.get(domain):
            referenced.update(await batch(provider_code, pending))
        else:
            for pointer in pending:
                if await checker(provider_code, pointer):
                    referenced.add(pointer)
    return referenced


async def prepare_content(
    content: bytes, provider_code: str = "native", *, content_type: str = "text",
) -> tuple[str, str | None]:
    from .resources import NativeFileStorage, get_storage

    provider = get_storage(provider_code)
    if provider_code == "native" and content_type in {"text", "json"} and type(provider) is NativeFileStorage:
        provider._validate_content(content)
        try:
            value = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ResourceStorageError("Resource text must be valid UTF-8") from None
        if "\x00" in value:
            raise ResourceStorageError("Resource text cannot contain NUL characters")
        return str(uuid4()), value
    return await provider.create(content), None
