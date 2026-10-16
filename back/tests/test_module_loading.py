"""Optional surfaces may be absent; broken active surfaces must be visible."""

from types import SimpleNamespace
import importlib
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
            "register_scheduler_jobs(scheduler.register_periodic_job); "
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


@pytest.mark.parametrize(("domain", "expected"), [
    ("chat", {"chat-web-push": (1.0, 900.0)}),
    ("llm", {"llm-running-call-reconciliation": (60.0, 900.0), "llm-document-analysis": (1.0, 1250.0)}),
    ("goal", {"goal-runner": (2.0, 900.0)}),
    ("lab", {"lab-operations": (1.0, 720.0), "lab-process-campaigns": (1.0, 900.0), "lab-mechanism-evaluations": (1.0, 900.0)}),
    ("voice", {"voice-turn-deletions": (2.0, 900.0)}),
])
def test_domain_jobs_use_the_injected_registrar(domain, expected):
    recorded = {}

    def register(name, callback, *, interval, timeout=900.0):
        assert callable(callback)
        recorded[name] = (interval, timeout)

    module = importlib.import_module(f"app.{domain}")
    module.register_scheduler_jobs(register)
    module.register_scheduler_jobs(register)
    assert recorded == expected


@pytest.mark.asyncio
async def test_process_job_refresh_keeps_the_injected_scheduler(monkeypatch):
    from app import process
    from core.params import Params, params_service

    listeners = []
    monkeypatch.setattr(params_service, "register_change_listener", listeners.append)
    register = Mock()
    unregister = Mock()
    await process.configure_default_engine(register, unregister)
    process.register_scheduler_jobs(register, unregister)
    initial = {call.args[0]: call.kwargs for call in register.call_args_list}
    register.reset_mock()
    await listeners[0](Params.PROCESS_REFRESH_STALENESS_SECONDS, "5")
    assert {call.args[0]: call.kwargs for call in register.call_args_list} == initial
    assert {call.args[0] for call in unregister.call_args_list} == {"process-outbox", "process-refresh"}


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
