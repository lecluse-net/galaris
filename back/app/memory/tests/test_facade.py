from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.memory import facade
from app.memory import router
from app.memory.contracts import MemorySearchItem
from app.memory.schemas import MemoryRecallRequest


@pytest.mark.asyncio
async def test_simple_search_facade_hides_scores_and_forwards_query_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory_id = uuid4()
    captured: list[MemoryRecallRequest] = []

    async def fake_recall(
        request: MemoryRecallRequest,
        *,
        record_llm_access: bool,
        telemetry_kind: str | None,
    ) -> SimpleNamespace:
        assert record_llm_access is False
        assert telemetry_kind is None
        captured.append(request)
        return SimpleNamespace(
            hits=[
                SimpleNamespace(
                    item=SimpleNamespace(
                        id=memory_id,
                        title="Release checklist",
                        memory_type="procedural",
                        node_kind="memory",
                        revision=3,
                    ),
                    excerpt="Validate the schema before deployment.",
                    score=0.987,
                    source_refs=["galaris://memory/source/42"],
                )
            ]
        )

    monkeypatch.setattr(facade, "recall_items", fake_recall)

    default_items = await facade.search_memory("safe deployment", agent_id=7)
    overridden_items = await facade.search_memory(
        "safe deployment",
        agent_id=7,
        semantic_query="Complete deployment objective and constraints",
        limit=3,
    )

    assert isinstance(default_items, list)
    assert default_items == overridden_items
    assert default_items[0].id == memory_id
    assert default_items[0].uri == f"memory://{memory_id}"
    assert default_items[0].revision == 3
    assert not hasattr(default_items[0], "score")
    assert captured[0].limit is None
    assert captured[1].limit == 3
    assert captured[1].semantic_query == (
        "Complete deployment objective and constraints"
    )


@pytest.mark.asyncio
async def test_facade_forwards_ranked_search_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[MemoryRecallRequest] = []

    async def fake_recall(
        request: MemoryRecallRequest,
        *,
        record_llm_access: bool,
        telemetry_kind: str | None,
    ) -> SimpleNamespace:
        captured.append(request)
        return SimpleNamespace(hits=[])

    monkeypatch.setattr(facade, "recall_items", fake_recall)

    assert await facade.search_memory(
        "architecture",
        agent_id=7,
        node_kinds=["memory"],
        exclude_source_managed=True,
    ) == []
    assert captured[0].node_kinds == ["memory"]
    assert captured[0].exclude_source_managed is True


@pytest.mark.asyncio
async def test_http_ranked_search_forwards_optional_overrides_to_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_search(text: str, **kwargs: object) -> list[MemorySearchItem]:
        captured.update({"text": text, **kwargs})
        return []

    monkeypatch.setattr(router.facade, "search_memory", fake_search)

    result = await router._ranked_memory_search(
        MemoryRecallRequest(
            agent_id=7,
            query="deployment",
            limit=3,
            node_kinds=["memory"],
            exclude_source_managed=True,
        )
    )

    assert result == []
    assert captured["text"] == "deployment"
    assert captured["limit"] == 3
    assert captured["node_kinds"] == ["memory"]
    assert captured["exclude_source_managed"] is True


def test_http_routes_separate_ranked_search_from_paginated_browse() -> None:
    paths = {route.path for route in router.router.routes}

    assert "/memory/search" in paths
    assert "/memory/browse" in paths
