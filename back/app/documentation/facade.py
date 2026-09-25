"""Documentation read port; callers enforce their transport's live authorization."""

from .contracts import Corpus, Page, Passage
from .corpus import load_corpus, page_at
from .search import SearchResult, index_embeddings, index_status, prune_retired, search

__all__ = ["Corpus", "Page", "Passage", "SearchResult", "load_corpus", "page_at",
           "index_embeddings", "index_status", "prune_retired", "search"]
