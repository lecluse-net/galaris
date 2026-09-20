"""SearXNG search helper used by MCP agent tools."""

from typing import Any

from app.util import SearchClient, SearchConnectionError, SearchRequestError, SearchResponse, SearchResult
from core.i18n import default_language, is_supported, render_prompt, t


# =============================================================================
# Search result formatting.
# =============================================================================

def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"tools.{key}", language), **values)


def _format_search_results(results: list[SearchResult], language: str = "") -> str:
    """Format search results for an agent."""
    lang = language if is_supported(language) else default_language()
    if not results:
        return _message(lang, "no_search_results")

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.title}")
        lines.append(f"   URL: {r.url}")
        lines.append(f"   Source: {r.engine}")
        if r.content:
            lines.append(f"   {_message(lang, 'summary', content=r.content)}")
        lines.append("")
    return "\n".join(lines)


def search_web(query: str, max_results: int = 5, *, language: str = "") -> str:
    """Search the web through SearXNG and return formatted results."""
    lang = language if is_supported(language) else default_language()
    try:
        client = SearchClient()
        return _format_response(client.search_response(query, max_results=max_results), lang)
    except Exception as exc:
        return _failure(exc, lang)


async def asearch_web(query: str, max_results: int = 5, *, language: str = "") -> str:
    """Use cancellable network I/O in an agent's event loop."""
    lang = language if is_supported(language) else default_language()
    try:
        response = await SearchClient().asearch_response(query, max_results=max_results)
        return _format_response(response, lang)
    except Exception as exc:
        return _failure(exc, lang)


def _format_response(response: SearchResponse, language: str) -> str:
    if not response.degraded:
        return _format_search_results(response.results, language)
    warning = _message(language, "search_partial" if response.results else "search_degraded",
        engines=response.unavailable_engine_count, discarded=response.discarded_result_count)
    return f"{warning}\n\n{_format_search_results(response.results, language)}" if response.results else warning


def _failure(exc: Exception, language: str) -> str:
    if isinstance(exc, SearchConnectionError):
        return _message(language, "search_unavailable")
    if isinstance(exc, SearchRequestError):
        if exc.reason == "timeout":
            return _message(language, "search_timeout")
        if exc.reason == "http":
            return _message(language, "search_http_failed", status=exc.status_code)
    return _message(language, "search_failed")
