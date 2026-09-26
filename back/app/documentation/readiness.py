"""Deployment checks for the shared corpus, independent of agent grants and providers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .contracts import Corpus
from .corpus import page_at


REQUIRED_SOURCES = (
    "README.md", "features.md", "user/navigation.md",
    "architecture/generated/navigation.md", "architecture/generated/navigation.json",
)


def content_revision(corpus: Corpus) -> str:
    """Compare sources across build labels, including renames and plan status changes."""
    digest = hashlib.sha256(b"galaris-documentation-content-v1")
    for page in sorted(corpus.pages, key=lambda page: page.path):
        digest.update(f"\0{page.path}\0{page.status}\0{page.checksum}".encode())
    return digest.hexdigest()


def check_corpus(corpus: Corpus, *, expected_revision: str | None = None) -> str:
    revision = content_revision(corpus)
    if expected_revision is not None and revision != expected_revision:
        raise ValueError("The running documentation differs from the prepared sources. Run make update to refresh images/mounts.")
    paths = {page.path for page in corpus.pages}
    for language in ("fr", "en"):
        for relative in REQUIRED_SOURCES:
            page = page_at(corpus, f"docs/{language}/{relative}")
            if not page.content.strip():
                raise ValueError(f"Empty documentation entrypoint: {page.path}")
    localized = {language: {path.removeprefix(f"docs/{language}/") for path in paths
                            if path.startswith(f"docs/{language}/")} for language in ("fr", "en")}
    if localized["fr"] != localized["en"]:
        missing = sorted(localized["fr"] ^ localized["en"])
        raise ValueError(f"Missing French/English documentation counterparts: {', '.join(missing[:20])}")
    return revision


@dataclass(frozen=True)
class DocumentationReady:
    content_revision: str
    corpus_revision: str
    build_version: str
    pages: int
    indexed_passages: int
    checked_languages: tuple[str, ...]


async def refresh_and_check(corpus: Corpus, *, expected_revision: str | None = None) -> DocumentationReady:
    """Synchronize lexical retrieval and prove that both navigation guides are retrievable.

    Runs in the caller's transaction. Semantic indexing remains incremental and never
    makes deployment depend on an external model. No agent/Tool permissions are changed.
    """
    from .search import index_status, search, synchronize

    revision = check_corpus(corpus, expected_revision=expected_revision)
    await synchronize(corpus)
    for language in ("fr", "en"):
        page = page_at(corpus, f"docs/{language}/user/navigation.md")
        result = await search(corpus, page.title, language=language, path_prefix=page.path, limit=1)
        if not result.hits or result.hits[0].uri != page.uri:
            raise ValueError(f"Navigation guide is not searchable: {page.path}")
        hit = result.hits[0]
        if hit.checksum != page.checksum or not page.content[hit.offset:hit.offset + hit.max_chars].strip():
            raise ValueError(f"Navigation search/read mismatch: {page.path}")
    status = await index_status(corpus, model_key=None)
    if status["indexed_passages"] != len(corpus.passages):
        raise ValueError("The current documentation lexical index is incomplete.")
    return DocumentationReady(revision, corpus.revision, corpus.build_version,
                              len(corpus.pages), len(corpus.passages), ("fr", "en"))
