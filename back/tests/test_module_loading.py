"""Optional surfaces may be absent; broken active surfaces must be visible."""

from types import SimpleNamespace
import subprocess
import sys
from unittest.mock import Mock
from unittest.mock import AsyncMock

from fastapi import APIRouter
import pytest

from core.database import model_loader
from core.util import router_loader
import modules


@pytest.mark.parametrize("first_module", ["app.task", "app.llm", "app.lab", "app.conversation", "app.process"])
def test_domain_scheduler_registration_in_fresh_interpreter(first_module):
    """Startup must not rely on MCP tests having imported operation services first."""
    result = subprocess.run(
        [sys.executable, "-c", (
            f"import {first_module}; "
            "from app.task import task_service, go_next, run_stream, scheduler; "
            "assert callable(task_service.get_by_id) and callable(go_next) and callable(run_stream); "
            "from app.lab import register_scheduler_jobs; "
            "register_scheduler_jobs(); "
            "from app.multimedia import generation_tick; "
            "from app.task import scheduler; "
            "scheduler.register_periodic_job('multimedia-generations', generation_tick, interval=1.0, timeout=720.0)"
        )],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("surface", ["app.task.task_service", "app.task.runner"])
def test_required_task_import_failure_is_visible(surface):
    script = f'''
import importlib.abc
import sys
class BrokenTaskSurface(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == {surface!r}:
            raise ImportError("synthetic required Task dependency failure")
sys.meta_path.insert(0, BrokenTaskSurface())
import app.task
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    assert "synthetic required Task dependency failure" in result.stderr


@pytest.mark.parametrize("surface", ["models", "router"])
def test_absent_optional_surface_is_skipped(monkeypatch, surface):
    monkeypatch.setattr(modules, "MODULES", ["example"])
    monkeypatch.setattr(router_loader, "MODULES", ["example"])
    monkeypatch.setattr(model_loader.importlib.util, "find_spec", lambda name: None)
    importer = Mock(side_effect=AssertionError("must not import absent surface"))
    monkeypatch.setattr(model_loader.importlib, "import_module", importer)
    if surface == "models":
        model_loader.load_models()
    else:
        router_loader.include_routers(APIRouter())
    importer.assert_not_called()


@pytest.mark.parametrize("surface", ["models", "router"])
@pytest.mark.parametrize("error", [ImportError("transitive dependency"), RuntimeError("broken module")])
def test_import_failure_propagates(monkeypatch, surface, error):
    monkeypatch.setattr(modules, "MODULES", ["example"])
    monkeypatch.setattr(router_loader, "MODULES", ["example"])
    monkeypatch.setattr(model_loader.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(model_loader.importlib, "import_module", Mock(side_effect=error))
    with pytest.raises(type(error), match=str(error)):
        if surface == "models":
            model_loader.load_models()
        else:
            router_loader.include_routers(APIRouter())


def test_explicitly_composed_router_module_is_allowed(monkeypatch):
    monkeypatch.setattr(router_loader, "MODULES", ["example"])
    monkeypatch.setattr(router_loader.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(router_loader.importlib, "import_module", lambda name: SimpleNamespace())
    router_loader.include_routers(APIRouter())


@pytest.mark.asyncio
async def test_broken_model_stops_orchestrator_before_database_or_atlas(monkeypatch):
    from core.dbadmin import orchestrator, DbAdminRegistry

    monkeypatch.setattr(modules, "MODULES", ["broken_model"])
    monkeypatch.setattr(model_loader.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(model_loader.importlib, "import_module", Mock(side_effect=ImportError("missing model dependency")))
    atlas = AsyncMock()
    wait_for_db = AsyncMock()
    monkeypatch.setattr(orchestrator, "apply_target", atlas)
    monkeypatch.setattr(orchestrator, "wait_for_db", wait_for_db)
    with pytest.raises(ImportError, match="missing model dependency"):
        await orchestrator.synchronize_database(target_registry=DbAdminRegistry())
    atlas.assert_not_awaited()
    wait_for_db.assert_not_awaited()
