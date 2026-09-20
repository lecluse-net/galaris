from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.catalog import (
    AgentToolCatalog,
    catalog_entry_from_definition,
    catalog_from_entries,
)
from app.tools.models import ToolSearchDocument
from app.tools import tool_search_service


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
        "_resolve_embedding_model",
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


@pytest.mark.asyncio
async def test_hybrid_search_prefilters_authorized_fingerprints(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del db
    model = tool_search_service.ToolEmbeddingModel(  # pyright: ignore[reportPrivateUsage]
        key="model-key",
        code="vector-test",
        model_name="vector-test",
        base_url="http://vector.test",
        api_key=None,
    )
    monkeypatch.setattr(
        tool_search_service,
        "_resolve_embedding_model",
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
    model = tool_search_service.ToolEmbeddingModel(  # pyright: ignore[reportPrivateUsage]
        key="stable-model-key",
        code="vector-test",
        model_name="vector-test",
        base_url="http://vector.test",
        api_key=None,
    )
    monkeypatch.setattr(
        tool_search_service,
        "_resolve_embedding_model",
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
        "_resolve_embedding_model",
        AsyncMock(return_value=None),
    )
    stale_catalog = _catalog(
        ("removed_remote_tool", "Tool no longer advertised"),
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
        "_resolve_embedding_model",
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

    async def successful_database_search(
        catalog: AgentToolCatalog,
        **_kwargs: object,
    ) -> tool_search_service.ToolSearchResult:
        return tool_search_service.ToolSearchResult(
            query="gitlab commits",
            catalog_version=catalog.version,
            mode="hybrid",
            hits=(),
        )

    monkeypatch.setattr(tool_search_service, "get_db_session", failing_commit)
    monkeypatch.setattr(
        tool_search_service,
        "search_catalog",
        successful_database_search,
    )

    result = await tool_search_service.search_catalog_in_isolated_session(
        catalog,
        query="gitlab commits",
        surface="test",
    )

    assert result.mode == "catalog_only"
    assert result.degraded is True
    assert result.degradation_reason == "search_transaction_unavailable"
    assert [hit.entry.name for hit in result.hits] == ["gitlab_list_commits"]
