import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.tools import mcp, search_tool
from app.tools.mcp_loader import McpToolContext
from app.util import SearchClient
from core.params import runtime_settings
from tests.manual.search import probe


def transport(monkeypatch, payload=None, *, status=200, handler=None):
    original = httpx.Client
    original_async = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        return handler(request) if handler else httpx.Response(status, json=payload)
    network = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=network, **kw))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original_async(transport=network, **kw))
    return requests


@pytest.mark.parametrize('language', ['fr', 'en'])
@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.asyncio
async def test_engine_failures_are_distinguished_from_no_matching_sources(monkeypatch, language, partial, asynchronous):
    transport(monkeypatch, {'results': [{'title': 'Useful source', 'url': 'https://example.org/source',
        'engine': 'available', 'content': 'Relevant excerpt'}] if partial else [],
        'unresponsive_engines': [['unavailable', 'CAPTCHA']]})
    result = (await search_tool.asearch_web('independent query', language=language)
              if asynchronous else search_tool.search_web('independent query', language=language))
    expected = ('partiel' if partial else 'dégradée') if language == 'fr' else ('partial' if partial else 'degraded')
    assert expected in result.lower()
    assert ('Useful source' in result) is partial
    assert 'Aucun résultat trouvé.' not in result and 'No results found.' not in result


@pytest.mark.parametrize('query', ['site:example.org "été & hiver" + archives', 'Python asyncio documentation', 'photosynthèse chlorophylle'])
def test_query_encoding_order_limits_and_configured_language_are_preserved(monkeypatch, query):
    monkeypatch.setattr(runtime_settings, 'SEARCH_DEFAULT_LANGUAGE', 'de')
    requests = transport(monkeypatch, {'results': [
        {'title': 'First', 'url': 'https://example.org/1'},
        {'title': 'Second', 'url': 'https://example.org/2'},
    ]})
    results = SearchClient().search(query, max_results=1)
    assert [r.title for r in results] == ['First']
    assert requests[0].url.params['q'] == query
    assert requests[0].url.params['language'] == 'de'
    assert requests[0].url.params['format'] == 'json'


@pytest.mark.parametrize('payload', [{}, [], {'results': None}])
def test_malformed_envelopes_are_not_reported_as_empty_searches(monkeypatch, payload):
    transport(monkeypatch, payload)
    result = search_tool.search_web('query', language='en')
    assert 'failed' in result.lower()
    assert 'No results found.' not in result


def test_invalid_entries_do_not_hide_valid_sources(monkeypatch):
    transport(monkeypatch, {'results': [None, {'title': 'No reference'},
        {'url': 'https://example.org/valid', 'title': 'Valid source'}]})
    result = search_tool.search_web('query', language='en')
    assert 'Valid source' in result and 'partial' in result.lower()


def test_transport_failure_does_not_expose_query_or_raw_exception(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout('query=PRIVATE-TEXT&token=SECRET', request=request)
    transport(monkeypatch, handler=fail)
    result = search_tool.search_web('PRIVATE-TEXT', language='en')
    assert 'SECRET' not in result and 'PRIVATE-TEXT' not in result
    assert 'timeout' in result.lower() or 'timed out' in result.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 403, 404, 429, 503])
async def test_mcp_keeps_healthy_empty_results_distinct_from_http_failures(monkeypatch, status):
    requests = transport(monkeypatch, {'results': [], 'private': 'UPSTREAM-SECRET'}, status=status)
    monkeypatch.setattr(runtime_settings, 'SEARCH_DEFAULT_LANGUAGE', 'de')
    monkeypatch.setattr(mcp, 'context_language', AsyncMock(return_value='en'))
    result = await mcp.search_web(McpToolContext(agent_id=7, runtime='internal'), 'test query')
    assert requests[0].url.params['language'] == 'de'
    assert 'UPSTREAM-SECRET' not in result
    if status == 200:
        assert result == 'No results found.'
    else:
        assert str(status) in result and 'failed' in result.lower()
        assert 'No results found.' not in result


@pytest.mark.parametrize('query, limit', [('', 5), ('   ', 5), ('valid', 0), ('valid', -1)])
def test_invalid_search_input_is_rejected_before_transport(monkeypatch, query, limit):
    requests = transport(monkeypatch, {'results': []})
    with pytest.raises(ValueError):
        SearchClient().search(query, max_results=limit)
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('partial, failures, expected', [
    (True, [], 0), (True, [['engine', 'CAPTCHA']], 2),
    (False, [], 1), (False, [['engine', 'CAPTCHA']], 1),
])
async def test_operational_probe_does_not_confuse_http_success_with_available_sources(
    monkeypatch, capsys, partial, failures, expected,
):
    transport(monkeypatch, {'results': [{'title': 'Source', 'url': 'https://example.org/source'}]
        if partial else [], 'unresponsive_engines': failures})
    assert await probe(SearchClient()) == expected
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert reports
    assert all(bool(report['sources']) == partial for report in reports)
    assert all(report['unavailable_engines'] == len(failures) for report in reports)


@pytest.mark.asyncio
async def test_operational_probe_reports_failed_transport_without_exposing_raw_error(monkeypatch, capsys):
    def fail(request):
        raise httpx.ConnectError('PRIVATE-CONNECTION-SECRET', request=request)
    transport(monkeypatch, handler=fail)
    assert await probe(SearchClient()) == 1
    output = capsys.readouterr().out
    assert 'PRIVATE-CONNECTION-SECRET' not in output
    assert all(json.loads(line)['status'] == 'failed' for line in output.splitlines())


@pytest.mark.asyncio
async def test_mcp_search_yields_during_network_wait_and_cancels_owned_request(monkeypatch):
    entered, closed = asyncio.Event(), asyncio.Event()
    async def response(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    # The old synchronous path completes instead of yielding to this controlled request.
    original_sync = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original_sync(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'results': []})), **kw))
    monkeypatch.setattr(mcp, 'context_language', AsyncMock(return_value='en'))
    pending = asyncio.create_task(mcp.search_web(McpToolContext(agent_id=7, runtime='internal'), 'query'))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not pending.done()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert closed.is_set()
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
