"""Read-only product documentation with live, function-level Galaris Admin grants."""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath

from app.documentation import facade as documentation
from app.tools import require_documentation_access

from .resource_contracts import ResourceContext, ResourceDescriptor, ResourceListing, ResourceRead
from .resource_uri import ResourceUri


class DocumentationRead(ResourceRead):
    corpus_revision: str
    checksum: str
    build_version: str
    offset_unit: str = "character"


async def _corpus(ctx: ResourceContext) -> documentation.Corpus:
    await require_documentation_access(ctx.agent_id)
    return await asyncio.to_thread(documentation.load_corpus)


def _path(reference: ResourceUri) -> str:
    return "/".join(reference.segments[1:])


def collection_descriptor(uri: str = "galaris://documentation/") -> ResourceDescriptor:
    return ResourceDescriptor(uri=uri, name="Galaris documentation", is_collection=True,
                              capabilities=["info", "list"], media_type="inode/directory")


def _descriptor(page: documentation.Page, corpus: documentation.Corpus) -> ResourceDescriptor:
    media_type = "application/json" if page.path.endswith(".json") else (
        "text/html" if page.path.endswith(".html") else "text/markdown"
    )
    return ResourceDescriptor(uri=page.uri, name=PurePosixPath(page.path).name,
        media_type=media_type, size=len(page.content.encode()), checksum=page.checksum,
        capabilities=["info", "read", "copy"], metadata={
            "title": page.title, "language": page.language, "domain": page.domain,
            "kind": page.kind, "status": page.status, "corpus_revision": corpus.revision,
            "build_version": corpus.build_version, "path": page.path,
        })


async def info(ctx: ResourceContext, reference: ResourceUri) -> ResourceDescriptor:
    corpus = await _corpus(ctx)
    path = _path(reference)
    if reference.is_collection:
        if path and not any(p.path.startswith(path + "/") for p in corpus.pages):
            raise FileNotFoundError("Documentation collection not found.")
        result = collection_descriptor(str(reference))
        result.metadata = {"corpus_revision": corpus.revision, "build_version": corpus.build_version,
                           "search_function": "documentation_search"}
        return result
    return _descriptor(documentation.page_at(corpus, path), corpus)


async def list_pages(ctx: ResourceContext, reference: ResourceUri, *, max_entries: int,
                     cursor: str | None) -> ResourceListing:
    corpus = await _corpus(ctx)
    if not reference.is_collection:
        raise ValueError("file_list requires a documentation collection URI.")
    prefix = _path(reference)
    pages = [p for p in corpus.pages if not prefix or p.path.startswith(prefix + "/")]
    if prefix and not pages:
        raise FileNotFoundError("Documentation collection not found.")
    offset = 0
    if cursor:
        revision, _, position = cursor.partition(":")
        if revision != corpus.revision or not position.isdecimal():
            raise ValueError("Documentation changed or cursor is invalid; list the collection again.")
        offset = int(position)
    limit = max(1, min(max_entries, 500))
    end = offset + limit
    return ResourceListing(uri=str(reference), entries=[_descriptor(p, corpus) for p in pages[offset:end]],
        truncated=end < len(pages), next_cursor=f"{corpus.revision}:{end}" if end < len(pages) else None)


async def read(ctx: ResourceContext, reference: ResourceUri, *, offset: int, max_chars: int) -> ResourceRead:
    corpus = await _corpus(ctx)
    if reference.is_collection:
        raise IsADirectoryError("Choose a documentation source URI from file_list or documentation_search.")
    page = documentation.page_at(corpus, _path(reference))
    start = max(0, min(offset, len(page.content)))
    end = min(len(page.content), start + max(1, min(max_chars, 100_000)))
    return DocumentationRead(uri=page.uri, content=page.content[start:end], media_type=_descriptor(page, corpus).media_type,
        start=start, end=end, total=len(page.content), next_offset=end if end < len(page.content) else None,
        checksum=page.checksum, corpus_revision=corpus.revision, build_version=corpus.build_version)
