from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

from core.database.middleware import _skip_db_session
from starlette.types import Scope


BACK_ROOT = Path(__file__).resolve().parents[2]

# Every entry is an autonomous async boundary: scheduler/worker, detached callback,
# listener, runtime gateway, or infrastructure orchestration. Application services
# and native MCP functions deliberately do not belong here.
ALLOWED_DATABASE_SESSION_BOUNDARIES = {
    "app/agent/openai_service.py",
    "app/chat/events.py",
    "app/chat/push_service.py",  # Post-commit signal receiver and delivery worker.
    "app/chat/storage.py",
    "app/chat/thumbnail_service.py",
    "app/chat/webrtc.py",  # Independent audio coroutines recheck revocation in short sessions.
    "app/conversation/facade.py",
    "app/conversation/scheduler.py",
    "app/conversation/service.py",
    "app/dream/attachment_processing.py",  # Attachment worker opens a session per model/media operation.
    "app/dream/mechanisms/attachment_memory.py",  # Scheduler claim/prepare/apply run without an ambient session.
    "app/dream/mechanisms/conversation_memory.py",
    "app/dream/mechanisms/document_structure.py",  # Autonomous reconciliation claims and applies separately.
    "app/dream/mechanisms/memory_maintenance.py",
    "app/dream/mechanisms/process_memory.py",
    "app/dream/mechanisms/sequential_topic_classification.py",
    "app/dream/mechanisms/skill_learning.py",
    "app/dream/mechanisms/stale_memory.py",
    "app/dream/mechanisms/task_memory.py",
    "app/dream/mechanisms/task_outcome_reflection.py",
    "app/dream/mechanisms/topic_classification.py",
    "app/dream/service.py",
    "app/harness/conversation.py",
    "app/harnesses/service.py",
    "app/incident/service.py",  # Isolated runtime telemetry; primary transactions are preserved.
    "app/llm/proxy_service.py",
    "app/llm/text_inference.py",  # Journal writer task commits independently of the caller.
    "app/llm/inference_execution.py",  # Independent admission, heartbeat and inference execution roots.
    "app/mcp/router.py",
    "app/memory/automation.py",
    "app/memory/html_migration.py",  # Read-only CLI audit under the __main__ guard.
    "app/memory/semantic_index.py",
    "app/messenger/journal.py",
    "app/messenger/native_facade.py",
    "app/messenger/service.py",
    "app/process/workers.py",  # Per-engine admission and observation roots; one session per branch.
    "app/task/activity.py",
    "app/task/live_checkpoint.py",  # Agent event callback persists independently of the run transaction.
    "app/task/agent_adapter.py",
    "app/task/scheduler.py",
    "app/tools/mcp_loader.py",
    "app/tools/tool_search_service.py",
    "app/voice/engine.py",
    "app/voice/realtime_engine.py",
    "app/voice/realtime_tools.py",
    "app/voice/session.py",
    "bridge/hermes/manager.py",
    "bridge/hermes/skill_sync.py",
    "bridge/matrix/voice_listener.py",
    "bridge/nextcloud/call_listener.py",
    "bridge/one_bot/router.py",
    "core/dbadmin/actions.py",
    "core/dbadmin/journal.py",
    "core/params/internal_secrets.py",  # Standalone post-migration verification CLI.
    "core/websocket.py",
    "main.py",
}


def _uses_database_session_factory(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(
            alias.name == "get_db_session" for alias in node.names
        ):
            return True
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == "get_db_session")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_db_session"
            )
        ):
            return True
    return False


def test_database_session_factory_stays_at_explicit_async_boundaries() -> None:
    """Services reuse get_db(); only audited roots may create a transaction."""

    actual: set[str] = set()
    for path in BACK_ROOT.rglob("*.py"):
        relative = path.relative_to(BACK_ROOT)
        if "tests" in relative.parts or "scripts" in relative.parts or path.name == "conftest.py":
            continue
        if relative.parts[:2] == ("core", "database"):
            continue
        if _uses_database_session_factory(path):
            actual.add(str(relative))

    assert actual == ALLOWED_DATABASE_SESSION_BOUNDARIES


def test_long_lived_channels_do_not_inherit_the_http_database_session() -> None:
    assert _skip_db_session(
        cast(Scope, {"path": "/socket.io/", "type": "websocket"})
    )
    assert _skip_db_session(
        cast(Scope, {"path": "/api/mcp/agent-code", "type": "http"})
    )
    assert not _skip_db_session(
        cast(Scope, {"path": "/api/agents/1", "type": "http"})
    )
