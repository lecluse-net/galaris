"""Capacity discovery is an external boundary; generation controls remain local rules."""

import asyncio
from collections import OrderedDict
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app.llm import generation_capacity as capacity
from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import ProviderConnection
from app.llm.request_parameters import RequestParameterPolicy, adapt_request_parameters


@pytest.fixture
def discovery(monkeypatch):
    monkeypatch.setattr(capacity, "_cache", OrderedDict())
    service = type("Catalog", (), {})()
    service.get_model_metadata = AsyncMock(return_value=LLMModelInfo(
        id="synthetic", context_length=131072, max_output_tokens=16384,
    ))
    monkeypatch.setattr(capacity, "model_metadata_for", lambda _: service)
    monkeypatch.setattr(capacity, "model_catalog_metadata", lambda: None)
    return service.get_model_metadata


def connection():
    return ProviderConnection(1, "Synthetic", None, "openai_compatible", "https://provider.invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol,key", [("chat", "max_tokens"), ("responses", "max_output_tokens")])
async def test_later_calls_reserve_context_for_history_tools_and_schemas(discovery, protocol, key):
    policy = RequestParameterPolicy()
    body = {"messages" if protocol == "chat" else "input": [{"role": "user", "content": "work"}]}
    result = await capacity.apply_generation_capacity(body, connection(), "synthetic", policy, protocol)
    assert result[key] == 16384
    assert key not in body
    discovery.return_value.context_length = 24000
    tools = [{"type": "function", "description": "a" * 42000,
        "parameters": {"type": "object", "properties": {"optional": {"type": ["string", "null"]}}}}]
    # Different model key: resolve a different serving capacity, never reuse the first.
    long = await capacity.apply_generation_capacity({**body, "tools": tools}, connection(), "other", policy, protocol)
    assert 1 < long[key] < 10000
    assert long["tools"] == tools


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["max_tokens", "max_completion_tokens", "max_output_tokens"])
async def test_explicit_budgets_skip_discovery_and_keep_existing_validation(discovery, key):
    policy = RequestParameterPolicy()
    for budget in [256, 0, -1, True]:
        body = {key: budget, "messages": []}
        result = await capacity.apply_generation_capacity(body, connection(), "synthetic", policy, "chat")
        assert result == body
        if budget == 256:
            assert adapt_request_parameters(result, policy, "chat")["max_tokens"] == 256
        else:
            with pytest.raises(ValueError):
                adapt_request_parameters(result, policy, "chat")
    discovery.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body,protocol,policy", [
    ({}, "compact", RequestParameterPolicy()),
    ({}, "responses", RequestParameterPolicy(responses=frozenset())),
    ({"previous_response_id": "remote"}, "responses", RequestParameterPolicy()),
    ({"conversation": "remote"}, "responses", RequestParameterPolicy()),
])
async def test_requests_without_local_generation_context_remain_unchanged(discovery, body, protocol, policy):
    assert await capacity.apply_generation_capacity(body, connection(), "synthetic", policy, protocol) == body
    discovery.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, OSError("offline"), TimeoutError()])
async def test_missing_discovery_is_cached_without_inventing_a_limit(discovery, failure):
    discovery.return_value = None
    discovery.side_effect = failure
    for _ in range(2):
        assert await capacity.apply_generation_capacity({}, connection(), "unknown", RequestParameterPolicy(), "chat") == {}
    assert discovery.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_discovery_expiry_and_connection_changes(discovery, monkeypatch):
    now = 1.0
    monkeypatch.setattr(capacity.time, "monotonic", lambda: now)

    async def lookup(*_):
        await asyncio.sleep(0)
        return LLMModelInfo(id="synthetic", context_length=131072, max_output_tokens=16384)

    discovery.side_effect = lookup
    async def read(conn):
        return await capacity.apply_generation_capacity({}, conn, "synthetic", RequestParameterPolicy(), "chat")

    assert all(result["max_tokens"] == 16384 for result in await asyncio.gather(*[read(connection()) for _ in range(5)]))
    assert discovery.await_count == 1
    now += 301
    await read(connection())
    assert discovery.await_count == 2
    await read(replace(connection(), base_url="https://changed.invalid"))
    await read(replace(connection(), api_key="synthetic-changed-key"))
    assert discovery.await_count == 4

    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_lookup(conn, _model):
        started.set()
        await release.wait()
        return LLMModelInfo(id="synthetic", context_length=131072, max_output_tokens=8192)

    discovery.side_effect = delayed_lookup
    old = asyncio.create_task(read(replace(connection(), base_url="https://old.invalid")))
    await started.wait()
    assert (await read(connection()))["max_tokens"] == 16384
    release.set()
    assert (await old)["max_tokens"] == 8192
    assert (await read(connection()))["max_tokens"] == 16384  # A late reply cannot replace the current connection.


@pytest.mark.asyncio
async def test_provider_capacity_wins_over_catalog_and_cancellation_propagates(discovery, monkeypatch):
    discovery.return_value = LLMModelInfo(id="synthetic", max_output_tokens=8192)
    fallback = type("Catalog", (), {})()
    fallback.get_model_metadata = AsyncMock(return_value=LLMModelInfo(
        id="synthetic", context_length=131072, max_output_tokens=32768,
    ))
    monkeypatch.setattr(capacity, "model_catalog_metadata", lambda: fallback)
    result = await capacity.apply_generation_capacity({}, connection(), "synthetic", RequestParameterPolicy(), "chat")
    assert result["max_tokens"] == 8192
    discovery.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await capacity.apply_generation_capacity({}, connection(), "cancelled", RequestParameterPolicy(), "chat")


@pytest.mark.asyncio
async def test_native_media_does_not_spend_context_as_base64_text(discovery):
    body = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "a" * 1000000}},
    ]}]}
    result = await capacity.apply_generation_capacity(body, connection(), "synthetic", RequestParameterPolicy(), "chat")
    assert result["max_tokens"] == 16384
    assert result["messages"] == body["messages"]
