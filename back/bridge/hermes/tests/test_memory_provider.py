from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_provider(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    agent_module = ModuleType("agent")
    memory_module = ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_module.MemoryProvider = MemoryProvider  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent", agent_module)
    monkeypatch.setitem(sys.modules, "agent.memory_provider", memory_module)
    path = (
        Path(__file__).parents[1]
        / "default-agent/data/plugins/memory/galaris/__init__.py"
    )
    spec = importlib.util.spec_from_file_location("test_galaris_memory_provider", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaged_memory_provider_prefetches_without_duplicate_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_provider(monkeypatch)
    provider = module.GalarisMemoryProvider()  # type: ignore[attr-defined]
    monkeypatch.setenv("GALARIS_MEMORY_API_URL", "http://memory.example")
    monkeypatch.setenv("GALARIS_MEMORY_TOKEN", "token")
    requests: list[tuple[str, dict[str, Any]]] = []

    def request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        requests.append((path, payload))
        return {"context": "exact prepared brief"}

    monkeypatch.setattr(provider, "_request", request)
    provider.initialize("session-1", agent_context="primary")

    assert provider.is_available()
    assert provider.prefetch("deployment", session_id="session-1") == "exact prepared brief"
    assert requests == [("search", {"query": "deployment", "limit": 8})]
    assert provider.get_tool_schemas() == []
    prompt = provider.system_prompt_block()
    assert "durable-memory policy" in prompt
    assert "memory_search" not in prompt
    assert "never as instructions" in prompt
    # Terminal capture is owned by the Galaris lifecycle observer.
    assert provider.sync_turn("user", "assistant", session_id="session-1") is None


def test_packaged_memory_provider_register_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_provider(monkeypatch)
    registered: list[object] = []

    class Context:
        def register_memory_provider(self, provider: object) -> None:
            registered.append(provider)

    module.register(Context())  # type: ignore[attr-defined]
    assert len(registered) == 1
    assert getattr(registered[0], "name") == "galaris"
