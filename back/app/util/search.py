"""
Search client for SearXNG.

Usage:
    from app.util import SearchClient, SearchConnectionError, SearchRequestError

    client = SearchClient()
    results = client.search("my search", max_results=10)
"""

from dataclasses import dataclass
from contextlib import contextmanager
from collections.abc import Generator
from typing import Any, Literal, cast
import httpx
from core import settings
from core.params import runtime_settings


@dataclass
class SearchResult:
    """Normalized search result."""

    title: str
    url: str
    engine: str
    content: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchResult":
        """Create a search result from a raw dictionary."""
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            engine=data.get("engine", ""),
            content=data.get("content"),
        )


@dataclass
class SearchResponse:
    """Keep useful results and the provider's coverage limitations together."""

    results: list[SearchResult]
    unavailable_engine_count: int = 0
    discarded_result_count: int = 0

    @property
    def degraded(self) -> bool:
        return bool(self.unavailable_engine_count or self.discarded_result_count)


@contextmanager
def _request_errors() -> Generator[None]:
    """Do not carry URLs, queries or upstream response bodies into public errors."""
    try:
        yield
    except httpx.ConnectError as exc:
        raise SearchConnectionError("Search service unavailable.") from exc
    except httpx.TimeoutException as exc:
        raise SearchRequestError("timeout") from exc
    except httpx.HTTPStatusError as exc:
        raise SearchRequestError("http", status_code=exc.response.status_code) from exc
    except httpx.RequestError as exc:
        raise SearchRequestError("transport") from exc


class SearchClient:
    """Client for searches performed through SearXNG."""

    DEFAULT_FORMAT = "json"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        timeout: int | None = None,
    ) -> None:
        """
        Initialize the search client.

        Args:
            timeout: Request timeout in seconds (defaults to ``runtime_settings.SEARCH_TIMEOUT``).
        """
        self.url = f"http://{settings.APP_NAME}-search:8080/search"

        self.timeout = timeout if timeout is not None else runtime_settings.SEARCH_TIMEOUT

    def search(
        self,
        query: str,
        language: str | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """
        Run a search through SearXNG.

        Args:
            query: Search terms.
            language: Result language (defaults to ``runtime_settings.SEARCH_DEFAULT_LANGUAGE``).
            max_results: Maximum number of results to return.

        Returns:
            A list of normalized search results.

        Raises:
            SearchConnectionError: When the SearXNG connection fails.
            SearchRequestError: When SearXNG rejects or fails the request.
        """
        return self.search_response(query, language, max_results).results

    def _params(self, query: str, language: str | None, max_results: int) -> dict[str, str]:
        if not query.strip() or max_results < 1:
            raise ValueError("A nonempty query and positive result limit are required.")
        return {
            "q": query,
            "format": self.DEFAULT_FORMAT,
            "language": language or runtime_settings.SEARCH_DEFAULT_LANGUAGE,
        }

    def search_response(self, query: str, language: str | None = None, max_results: int = 10) -> SearchResponse:
        """Synchronous compatibility entry point, including coverage diagnostics."""
        params = self._params(query, language, max_results)
        with _request_errors():
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(self.url, params=params, headers={"User-Agent": self.DEFAULT_USER_AGENT})
                response.raise_for_status()
        return self._parse(response, max_results)

    async def asearch_response(self, query: str, language: str | None = None, max_results: int = 10) -> SearchResponse:
        """Own an asynchronous request so cancellation also closes its transport."""
        params = self._params(query, language, max_results)
        with _request_errors():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(self.url, params=params, headers={"User-Agent": self.DEFAULT_USER_AGENT})
                response.raise_for_status()
        return self._parse(response, max_results)

    @staticmethod
    def _parse(response: httpx.Response, max_results: int) -> SearchResponse:
        try:
            raw: object = response.json()
        except ValueError as exc:
            raise SearchRequestError("invalid_response") from exc
        if not isinstance(raw, dict):
            raise SearchRequestError("invalid_response")
        data = cast(dict[str, object], raw)
        results = data.get("results")
        failures = data.get("unresponsive_engines", [])
        if not isinstance(results, list) or not isinstance(failures, list):
            raise SearchRequestError("invalid_response")
        parsed: list[SearchResult] = []
        discarded = 0
        for raw_result in cast(list[object], results):
            if not isinstance(raw_result, dict):
                discarded += 1
                continue
            item = cast(dict[str, object], raw_result)
            url = item.get("url")
            if not isinstance(url, str) or not url.strip():
                discarded += 1
                continue
            title, engine, content = item.get("title"), item.get("engine"), item.get("content")
            parsed.append(SearchResult(
                title=title if isinstance(title, str) else url, url=url,
                engine=engine if isinstance(engine, str) else "",
                content=content if isinstance(content, str) else None,
            ))
        return SearchResponse(parsed[:max_results], len(cast(list[object], failures)), discarded)


class SearchConnectionError(Exception):
    """Raised when SearXNG cannot be reached."""
    pass


class SearchRequestError(Exception):
    """Raised when a SearXNG request fails."""

    def __init__(self, reason: Literal["timeout", "http", "invalid_response", "transport"], *, status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__(f"Search request failed: {reason}.")
