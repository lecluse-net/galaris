"""Reader port bound by application composition, without an LLM-domain dependency."""

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import JsonValue
from core.document import PreparedDocument


class DocumentRetrievalCache(Protocol):
    async def load(self, fingerprint: str) -> dict[str, JsonValue] | None: ...
    async def save(self, fingerprint: str, payload: dict[str, JsonValue]) -> None: ...


class RetrievedPassage(Protocol):
    @property
    def page(self) -> int | None: ...
    @property
    def start(self) -> int: ...
    @property
    def end(self) -> int: ...
    @property
    def text(self) -> str: ...
    @property
    def kind(self) -> Literal['page', 'structured']: ...


class RetrievedDocument(Protocol):
    @property
    def mode(self) -> Literal['hybrid', 'lexical']: ...
    @property
    def indexed_passages(self) -> int: ...
    @property
    def selected_passages(self) -> int: ...
    @property
    def selected_pages(self) -> Sequence[int]: ...
    @property
    def passages(self) -> Sequence[RetrievedPassage]: ...
    @property
    def warnings(self) -> Sequence[str]: ...


class DocumentRetriever(Protocol):
    async def __call__(self, document: PreparedDocument, query: str, *, token_budget: int,
                       cache: DocumentRetrievalCache | None = None,
                       use_embeddings: bool = True) -> RetrievedDocument: ...


_reader: DocumentRetriever | None = None


def register_document_retriever(reader: DocumentRetriever) -> None:
    global _reader
    _reader = reader


async def retrieve_document(document: PreparedDocument, query: str, *, token_budget: int,
                            cache: DocumentRetrievalCache | None, use_embeddings: bool) -> RetrievedDocument:
    if _reader is None:
        raise RuntimeError('Document retrieval is not configured')
    return await _reader(document, query, token_budget=token_budget, cache=cache, use_embeddings=use_embeddings)
