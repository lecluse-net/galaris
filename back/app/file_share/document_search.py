"""Source-authorized, bounded document retrieval through the existing file tool."""

from pathlib import Path
from typing import Any, Literal

from core.document import OFFICE_EXTENSIONS
from .resource_contracts import ResourceContext, ResourceDescriptor, ResourceSearchHit, ResourceSearchResult


def supports_document_search(info: ResourceDescriptor) -> bool:
    return (info.media_type.split(';', 1)[0] == 'application/pdf' or info.media_type.startswith('text/')
            or Path(info.name).suffix.lower() in OFFICE_EXTENSIONS | {
                '.pdf', '.md', '.html', '.htm', '.epub', '.txt', '.csv', '.tsv', '.json', '.xml'})


async def search_document(
    ctx: ResourceContext, info: ResourceDescriptor, query: str, *, mode: Literal['text', 'semantic'],
    cursor: str | None = None,
) -> ResourceSearchResult:
    from .document_retrieval import retrieve_document
    from .document_facade import prepared_resource
    from .document_rag_cache import document_rag_cache
    from .resource_service import resource_info

    if not 1 <= len(query.strip()) <= 8000:
        raise ValueError('Document search requires a non-empty query of at most 8000 characters')
    if cursor:
        raise ValueError('Single-file search returns one bounded file hit; refine the query instead of using a cursor')
    if not supports_document_search(info):
        raise NotImplementedError('This file has no documentary text reader; use file_read or its specialized media tool')
    fields = {'name', 'media_type', 'size', 'revision', 'checksum', 'etag', 'modified_at'}
    async with prepared_resource(ctx, info.uri) as (document, _directory):
        # Lexical requests never replace an existing semantic generation or call
        # an embedding provider. Semantic requests share the source-owned cache.
        cache = await document_rag_cache(ctx, info.uri, document.sha256) if mode == 'semantic' else None
        selection = await retrieve_document(document, query.strip(), token_budget=1800,
            cache=cache, use_embeddings=mode == 'semantic')
        after = await resource_info(ctx, info.uri)
        if after.model_dump(include=fields) != info.model_dump(include=fields):
            raise ValueError('Document changed during search; read current metadata and retry')
        coverage: dict[str, Any] = {
            **document.coverage(), 'source_sha256': document.sha256,
            'indexed_passages': selection.indexed_passages,
            'selected_passages': selection.selected_passages,
            'selected_pages': list(selection.selected_pages), 'exhaustive': False,
            'offset_unit': 'character', 'warnings': list(selection.warnings),
            'full_analysis_tool': 'document_analyze',
        }
        degraded = mode == 'semantic' and selection.mode == 'lexical'
        return ResourceSearchResult(uri=info.uri, query=query.strip(), mode=mode,
            hits=[ResourceSearchHit(resource=after, excerpt=' '.join(selection.warnings),
                passages=[{'page': passage.page, 'start': passage.start, 'end': passage.end,
                           'text': passage.text, 'kind': passage.kind} for passage in selection.passages],
                retrieval_sources=['document-rag'], source_refs=[info.uri])] if selection.passages else [],
            retrieval_mode=selection.mode, degraded=degraded,
            degradation_reason='; '.join(selection.warnings) if degraded else None,
            relevance_status='matched' if selection.passages else 'no_sufficient_evidence',
            index_coverage=coverage, truncated=False)
