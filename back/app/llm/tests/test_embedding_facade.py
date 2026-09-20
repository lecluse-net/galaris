from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.llm import embedding_facade


@pytest.mark.asyncio
async def test_semantic_ranking_returns_every_index_in_similarity_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SimpleNamespace(is_active=True, api_key="encrypted")
    llm = SimpleNamespace(provider=provider, llm_name="multilingual-embedding")
    calls: list[list[str]] = []

    async def embed_many(
        texts: list[str],
        *,
        endpoint: object,
        timeout_seconds: float,
    ) -> list[list[float]]:
        del endpoint
        assert timeout_seconds == 5.0
        calls.append(texts)
        if texts == ["facture fournisseur"]:
            return [[1.0, 0.0]]
        return [
            [0.0, 1.0],
            [0.8, 0.2],
            [1.0, 0.0],
        ]

    monkeypatch.setattr(
        embedding_facade.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=llm),
    )
    monkeypatch.setattr(
        embedding_facade,
        "provider_connection",
        lambda _provider, _api_key: object(),
    )
    monkeypatch.setattr(
        embedding_facade,
        "openai_protocol_base_url",
        lambda _connection: "https://embedding.example/v1",
    )
    monkeypatch.setattr(
        embedding_facade.llm_provider_service,
        "decrypt_api_key",
        lambda _value: "secret",
    )
    monkeypatch.setattr(embedding_facade.embedding_service, "embed_many", embed_many)

    ranked = await embedding_facade.rank_texts_by_semantic_similarity(
        "facture fournisseur",
        ["Weather", "Supplier", "Invoice"],
    )

    assert ranked == (2, 1, 0)
    assert calls == [
        ["facture fournisseur"],
        ["Weather", "Supplier", "Invoice"],
    ]


@pytest.mark.asyncio
async def test_semantic_ranking_is_absent_without_a_vector_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        embedding_facade.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=None),
    )

    assert (
        await embedding_facade.rank_texts_by_semantic_similarity(
            "request",
            ["candidate"],
        )
        is None
    )
