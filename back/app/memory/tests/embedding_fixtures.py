"""Small published generations for ranking fixtures with prescribed vectors."""

from core.database import get_db
from app.memory.models import MemoryEmbeddingChunk, MemoryEmbeddingManifest
from app.memory.semantic_index import SEMANTIC_INDEX_VERSION


def published_chunk(**values):
    chunk = MemoryEmbeddingChunk(**values)
    get_db().add(MemoryEmbeddingManifest(
        item_id=chunk.item_id, source_fingerprint=chunk.source_fingerprint,
        model_key=chunk.model_key, dimensions=chunk.dimensions,
        chunk_count=1, index_version=SEMANTIC_INDEX_VERSION,
        source_word_count=len(chunk.text.split()), indexed_word_count=len(chunk.text.split()),
    ))
    return chunk
