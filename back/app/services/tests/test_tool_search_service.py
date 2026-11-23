from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.catalog import (
    AgentToolCatalog,
    catalog_entry_from_definition,
    catalog_from_entries,
)
from app.services.models import ToolSearchDocument
from app.services import tool_search_service


@pytest.mark.asyncio
async def test_eight_tool_searches_can_reach_the_provider_concurrently(
    committed_database, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.database import get_db_session

    catalog = _catalog(("synthetic_room_history", "Read room messages"))
    model = tool_search_service.ConfiguredEmbeddingModel(
        key="synthetic", code="synthetic", model_name="synthetic", base_url="http://vector.test",
    )
    monkeypatch.setattr(tool_search_service, "configured_embedding_model", AsyncMock(return_value=model))
    release = asyncio.Event()
    all_at_provider = asyncio.Event()
    queries = 0
    refreshes = 0

    async def embed(texts: list[str], **_kwargs: object) -> list[list[float]]:
        nonlocal queries, refreshes
        if texts[0].startswith("room messages"):
            queries += 1
            if queries == 8:
                all_at_provider.set()
            await release.wait()
        else:
            refreshes += 1
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(tool_search_service, "_embed_many", embed)
    searches = [asyncio.create_task(tool_search_service.search_catalog_in_isolated_session(
        catalog, query=f"room messages {index}", surface="test",
    )) for index in range(8)]
    try:
        async with asyncio.timeout(5):
            await all_at_provider.wait()
            # A ninth transaction can update this fingerprint while queries
            # wait on the provider; the repository must hold no row lock.
            async with get_db_session() as db:
                assert (await db.scalars(select(ToolSearchDocument).where(
                    ToolSearchDocument.definition_fingerprint == catalog.entries[0].definition_fingerprint,
                ).with_for_update(nowait=True))).one()
        release.set()
        results = await asyncio.gather(*searches)
        assert all(result.mode == "hybrid" for result in results)
        assert refreshes == 1
    finally:
        release.set()
        for search in searches:
            if not search.done():
                search.cancel()
        await asyncio.gather(*searches, return_exceptions=True)


def _catalog(*definitions: tuple[str, str]) -> AgentToolCatalog:
    return catalog_from_entries(
        agent_id=12,
        runtime="internal",
        entries=[
            catalog_entry_from_definition(
                runtime="internal",
                name=name,
                description=description,
                parameters_json_schema={"type": "object", "properties": {}},
            )
            for name, description in definitions
        ],
    )


@pytest.mark.asyncio
async def test_lexical_search_indexes_only_effective_catalog(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tool_search_service,
        "configured_embedding_model",
        AsyncMock(return_value=None),
    )
    catalog = _catalog(
        ("messenger_room_history", "Read recent messages from a room"),
        ("weather_forecast", "Get a weather forecast"),
    )

    result = await tool_search_service.search_catalog(
        catalog,
        query="historique messages room",
        surface="test",
    )

    assert result.mode == "lexical"
    assert result.degraded is True
    assert [hit.entry.name for hit in result.hits] == [
        "messenger_room_history"
    ]
    indexed = set(
        await db.scalars(select(ToolSearchDocument.definition_fingerprint))
    )
    assert indexed == {
        entry.definition_fingerprint for entry in catalog.entries
    }

    # A policy change needs no explicit index refresh: revoked definitions may
    # remain in the shared index, but cannot appear in the next effective search.
    # Newly allowed definitions become searchable on that same next request.
    changed = _catalog(("messenger_room_export", "Export room messages"))
    next_result = await tool_search_service.search_catalog(
        changed, query="room messages", surface="test",
    )
    assert [hit.entry.name for hit in next_result.hits] == ["messenger_room_export"]
    assert await db.scalar(select(ToolSearchDocument).where(
        ToolSearchDocument.name == "messenger_room_history",
    )) is not None


@pytest.mark.asyncio
async def test_hybrid_search_prefilters_authorized_fingerprints(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del db
    model = tool_search_service.ConfiguredEmbeddingModel(  # pyright: ignore[reportPrivateUsage]
        key="model-key",
        code="vector-test",
        model_name="vector-test",
        base_url="http://vector.test",
        api_key=None,
    )
    monkeypatch.setattr(
        tool_search_service,
        "configured_embedding_model",
        AsyncMock(return_value=model),
    )

    async def fake_embed_many(
        texts: list[str],
        *,
        model: object,
        timeout_seconds: float,
    ) -> list[list[float]]:
        del model, timeout_seconds
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [1.0, 0.0]
                if "room" in lowered or "message" in lowered
                else [0.0, 1.0]
            )
        return vectors

    monkeypatch.setattr(tool_search_service, "_embed_many", fake_embed_many)
    all_tools = _catalog(
        ("messenger_room_history", "Read recent messages from a room"),
        ("admin_delete_everything", "Delete all messages from a room"),
        ("weather_forecast", "Get a weather forecast"),
    )
    await tool_search_service.search_catalog(
        all_tools,
        query="weather",
        surface="test",
    )

    authorized = _catalog(
        ("messenger_room_history", "Read recent messages from a room"),
        ("weather_forecast", "Get a weather forecast"),
    )
    result = await tool_search_service.search_catalog(
        authorized,
        query="room messages",
        surface="test",
    )

    names = [hit.entry.name for hit in result.hits]
    assert result.mode == "hybrid"
    assert names[0] == "messenger_room_history"
    assert "admin_delete_everything" not in names


@pytest.mark.asyncio
async def test_hybrid_search_reembeds_when_provider_dimensions_change(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = tool_search_service.ConfiguredEmbeddingModel(  # pyright: ignore[reportPrivateUsage]
        key="stable-model-key",
        code="vector-test",
        model_name="vector-test",
        base_url="http://vector.test",
        api_key=None,
    )
    monkeypatch.setattr(
        tool_search_service,
        "configured_embedding_model",
        AsyncMock(return_value=model),
    )
    dimensions = 2

    async def fake_embed_many(
        texts: list[str],
        *,
        model: object,
        timeout_seconds: float,
    ) -> list[list[float]]:
        del model, timeout_seconds
        return [[1.0, *([0.0] * (dimensions - 1))] for _text in texts]

    monkeypatch.setattr(tool_search_service, "_embed_many", fake_embed_many)
    catalog = _catalog(("messenger_room_history", "Read room messages"))

    first = await tool_search_service.search_catalog(
        catalog,
        query="room messages",
        surface="test",
    )
    dimensions = 3
    second = await tool_search_service.search_catalog(
        catalog,
        query="room messages",
        surface="test",
    )

    document = await db.scalar(select(ToolSearchDocument))
    assert first.mode == "hybrid"
    assert second.mode == "hybrid"
    assert document is not None
    assert document.dimensions == 3
    assert len(document.embedding or []) == 3


@pytest.mark.asyncio
async def test_forced_refresh_prunes_stale_documents_after_complete_snapshot(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tool_search_service,
        "configured_embedding_model",
        AsyncMock(return_value=None),
    )
    stale_catalog = _catalog(
        ("removed_remote_tool", "Service no longer advertised"),
        ("weather_forecast", "Read the weather forecast"),
    )
    await tool_search_service.search_catalog(
        stale_catalog,
        query="weather",
        surface="test",
    )
    current_catalog = _catalog(
        ("weather_forecast", "Read the weather forecast"),
    )

    result = await tool_search_service.refresh_catalog_index(
        [current_catalog],
        force_embeddings=True,
        prune_stale=True,
    )

    names = set(await db.scalars(select(ToolSearchDocument.name)))
    assert names == {"weather_forecast"}
    assert result.documents_indexed == 1
    assert result.documents_pruned == 1
    assert result.semantic_available is False
    assert result.degradation_reason == "embedding_not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("send a message to a room", "messenger_room_send_message"),
        ("weather forecast", "weather_forecast"),
        ("transcribe an audio recording", "audio_transcribe"),
        ("start a long workflow process", "process_start"),
    ],
)
async def test_lexical_discovery_corpus_returns_expected_tool_first(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    expected: str,
) -> None:
    del db
    monkeypatch.setattr(
        tool_search_service,
        "configured_embedding_model",
        AsyncMock(return_value=None),
    )
    catalog = _catalog(
        ("messenger_room_send_message", "Send a message to a conversation room"),
        ("weather_forecast", "Get the weather forecast for a location"),
        ("audio_transcribe", "Transcribe an audio recording into text"),
        ("process_start", "Start a long-running workflow process"),
        ("file_write", "Write text to a provider file"),
    )

    result = await tool_search_service.search_catalog(
        catalog,
        query=query,
        surface="test",
    )

    assert result.hits
    assert result.hits[0].entry.name == expected


@pytest.mark.asyncio
async def test_isolated_search_rolls_back_before_database_free_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog(
        ("gitlab_list_commits", "List recent GitLab repository commits"),
        ("weather_forecast", "Get a weather forecast"),
    )

    @asynccontextmanager
    async def failing_commit() -> AsyncIterator[None]:
        yield
        raise RuntimeError("transaction invalidated during commit")

    monkeypatch.setattr(tool_search_service, "get_db_session", failing_commit)
    monkeypatch.setattr(tool_search_service, "_read_index_state", AsyncMock(return_value={}))
    monkeypatch.setattr(tool_search_service, "_insert_documents", AsyncMock())
    monkeypatch.setattr(tool_search_service, "_lexical_fingerprints", AsyncMock(return_value=[]))

    result = await tool_search_service.search_catalog_in_isolated_session(
        catalog,
        query="gitlab commits",
        surface="test",
    )

    assert result.mode == "catalog_only"
    assert result.degraded is True
    assert result.degradation_reason == "search_transaction_unavailable"
    assert [hit.entry.name for hit in result.hits] == ["gitlab_list_commits"]
