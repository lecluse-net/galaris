"""
Utilitaires applicatifs.
"""

from .search import (
    SearchClient,
    SearchResult,
    SearchResponse,
    SearchConnectionError,
    SearchRequestError,
)

__all__ = [
    "SearchClient",
    "SearchResult",
    "SearchResponse",
    "SearchConnectionError",
    "SearchRequestError",
]
