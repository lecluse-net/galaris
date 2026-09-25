"""
FastAPI application entry point.

This module composes the public API and runtime services.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from core.api import create_app, setup_public_docs, setup_api_routers
from core import websocket
from modules import configure_dream_media, load_llm_provider_modules


# Provider bridges register immutable profiles and optional service adapters.
# Loading them is a composition concern; application domains never import bridge code.
load_llm_provider_modules()

# Cross-cutting execution domains emit through a core port; the composition root
# binds its PostgreSQL implementation without creating reverse domain imports.
from app.incident import register_runtime as register_incident_runtime

register_incident_runtime()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown."""
    from app.agent import register_briefing_output_contracts, register_dispatcher_output_contracts
    from app.lab import register_inference_output_contracts as register_lab_output_contracts

    register_dispatcher_output_contracts()
    register_briefing_output_contracts()
    register_lab_output_contracts()
    # Wait for database availability before the first query so a transient DNS
    # or remote startup delay cannot terminate Uvicorn permanently.
    from core.database import get_db_session, wait_for_db
    await wait_for_db()

    # Database-backed application parameters must be loaded before runtime
    # services start reading their typed in-memory view.
    from core.params import params_service
    async with get_db_session():
        # DbAdmin has already reconciled persistent datasets in the entrypoint.
        # Runtime startup only hydrates the process-local parameter cache.
        await params_service.load_params()
        from core.observability import configure_runtime_observability
        await configure_runtime_observability()
        from app.process import configure_default_engine, register_scheduler_jobs
        from app.llm import register_scheduler_jobs as register_llm_scheduler_jobs
        from app.goal import register_scheduler_jobs as register_goal_jobs
        from app.lab import register_scheduler_jobs as register_lab_jobs
        from bridge.calendar import sync_calendars
        from app.task import register_runtime_settings, scheduler as task_scheduler
        from app.chat import reconcile_storage, register_scheduler_jobs as register_chat_jobs
        from app.incident import prune_traces as prune_incident_traces
        from app.llm import prune_traces as prune_llm_traces
        from core.user.refresh_session_service import purge_expired_sessions
        from core.observability import record_runtime_pressure
        from core.database.storage import record_storage_metrics
        from app.process.progress import record_progress_metrics as record_process_progress
        from app.task.progress import record_progress_metrics as record_task_progress
        from app.conversation.progress import record_progress_metrics as record_conversation_progress

        await configure_default_engine()
        register_runtime_settings()
        from app.task import reconcile_replacements, register_replacement_blocker
        from app.process import replacement_blocked_task_ids
        register_replacement_blocker("process", replacement_blocked_task_ids)
        task_scheduler.register_periodic_job("task-replacements", reconcile_replacements, interval=2.0)
        register_llm_scheduler_jobs()
        from app.tools.documentation_service import refresh_documentation_index
        task_scheduler.register_periodic_job(
            "documentation-index", refresh_documentation_index, interval=30.0, timeout=45.0,
        )
        register_scheduler_jobs()
        register_goal_jobs()
        register_lab_jobs()
        register_chat_jobs(task_scheduler.register_periodic_job)
        for name, observer in (
            ("runtime-pressure", record_runtime_pressure), ("process-progress", record_process_progress),
            ("task-progress", record_task_progress), ("notification-progress", record_conversation_progress),
        ):
            task_scheduler.register_periodic_job(name, observer, interval=10.0, timeout=10.0)
        task_scheduler.register_periodic_job(
            "database-storage", record_storage_metrics, interval=3_600.0,
        )
        task_scheduler.register_periodic_job(
            "incident-trace-retention", prune_incident_traces, interval=3_600.0,
        )
        task_scheduler.register_periodic_job(
            "llm-trace-retention", prune_llm_traces, interval=3_600.0,
        )
        task_scheduler.register_periodic_job(
            "expired-browser-sessions", purge_expired_sessions, interval=3_600.0,
        )
        task_scheduler.register_periodic_job(
            "calendar-sync", sync_calendars, interval=15 * 60.0
        )
        task_scheduler.register_periodic_job(
            "chat-storage-reconciliation",
            reconcile_storage,
            interval=3_600.0,
        )

    # The native provider has no remote listener able to redeliver a message
    # interrupted between journal persistence and conversation admission.
    from app.messenger import reconcile_internal_admissions
    await reconcile_internal_admissions()

    # Root services retain their domain-owned recovery logic. The generic
    # supervisor only observes and restarts their in-memory root tasks.
    from sqlalchemy import text
    from core.runtime import (
        RuntimeComponent,
        RuntimeProbe,
        runtime_supervisor,
    )
    from app.messenger import start_listeners, stop_listeners, listeners_running
    from app.llm.facade import (
        start_inference_worker,
        stop_inference_worker,
        inference_worker_running,
    )
    from app.memory.automation import (
        memory_automation_running,
        start_memory_automation,
        stop_memory_automation,
    )
    from app.dream import (
        is_running as dream_is_running,
        start as start_dream,
        stop as stop_dream,
    )
    configure_dream_media()
    from app.task import scheduler as task_scheduler
    from app.conversation import register_controller, register_runtime
    from app.conversation import scheduler as conversation_scheduler
    from app.harness.conversation import HarnessConversationController
    from app.voice import (
        start_voice_call_listeners,
        stop_voice_call_listeners,
        voice_call_listeners_running,
    )

    async def start_task_scheduler() -> None:
        task_scheduler.start()

    async def start_conversation_scheduler() -> None:
        conversation_scheduler.start()

    register_controller(HarnessConversationController())
    register_runtime()

    async def database_ready() -> bool:
        from core.database import engine

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True

    runtime_supervisor.configure(
        (
            RuntimeComponent(
                name="websocket_sessions",
                start=websocket.start_session_monitor,
                stop=websocket.stop_session_monitor,
                is_running=websocket.session_monitor_running,
            ),
            RuntimeComponent(
                name="llm_inference_worker",
                start=start_inference_worker,
                stop=stop_inference_worker,
                is_running=inference_worker_running,
            ),
            RuntimeComponent(
                name="task_scheduler",
                start=start_task_scheduler,
                stop=task_scheduler.stop,
                is_running=task_scheduler.is_running,
            ),
            RuntimeComponent(
                name="conversation_scheduler",
                start=start_conversation_scheduler,
                stop=conversation_scheduler.stop,
                is_running=conversation_scheduler.is_running,
            ),
            RuntimeComponent(
                name="messenger_listeners",
                start=start_listeners,
                stop=stop_listeners,
                is_running=listeners_running,
                critical=False,
            ),
            RuntimeComponent(
                name="memory_automation",
                start=start_memory_automation,
                stop=stop_memory_automation,
                is_running=memory_automation_running,
                critical=False,
            ),
            RuntimeComponent(
                name="voice_listeners",
                start=start_voice_call_listeners,
                stop=stop_voice_call_listeners,
                is_running=voice_call_listeners_running,
                critical=False,
            ),
            RuntimeComponent(
                name="dream_scheduler",
                start=start_dream,
                stop=stop_dream,
                is_running=dream_is_running,
                critical=False,
            ),
        ),
        probes=(RuntimeProbe(name="database", check=database_ready),),
    )

    try:
        await runtime_supervisor.start()
        yield
    finally:
        # Shut down runtime services in reverse order.
        await runtime_supervisor.stop()
        websocket.stop()
        # Dispose the pool before reload/shutdown so asyncpg connections do not
        # reach garbage collection while still open.
        from core.database import engine
        await engine.dispose()


# Create the FastAPI application and middleware stack.
app = create_app(lifespan)

# Configure public documentation.
setup_public_docs(app)

# Include public API routers; discovery also registers bridges.
setup_api_routers(app)

# The composition root, not core, mounts bridge-specific routes.
from bridge.one_bot import onebot_router
app.include_router(onebot_router)

# Scan @authorize routes only after all routers are registered; otherwise the
# global guard would treat unseen routes as unprotected.
from core.authorize import AuthorizeService
AuthorizeService().start(app)

# Register messaging resolution after every bridge is available.
from app.messenger import register_messaging
register_messaging()
from app.voice import register_runtime_settings as register_voice_settings

register_voice_settings()

# Goal consumes the canonical Contact directory through its own injected port,
# keeping both application domains independent outside this composition root.
from app.contact import list_reachable_humans
from app.goal import GoalHumanContact, register_goal_contact_directory


class GoalContactDirectoryAdapter:
    async def list_humans(
        self, *, agent_id: int, query: str
    ) -> tuple[GoalHumanContact, ...]:
        contacts = await list_reachable_humans(agent_id=agent_id, query=query)
        return tuple(
            GoalHumanContact(
                connection_id=contact.connection_id,
                tool_id=contact.tool_id,
                platform=contact.platform,
                user_id=contact.user_id,
                display_name=contact.display_name,
                galaris_user_id=contact.galaris_user_id,
            )
            for contact in contacts
        )


register_goal_contact_directory(GoalContactDirectoryAdapter())

# Context composition is driver-neutral: both internal and Hermes runs receive
# the same governed long-term and Messenger-session snapshots.
from app.memory import register_memory
register_memory()
from app.agent import register_default_agent
register_default_agent()
from app.browser import capture_html_page_thumbnail, capture_public_page_thumbnail
from app.memory.document_thumbnail_service import register_web_thumbnail_capture


from core.user import HumanActor


async def capture_document_web_thumbnail(
    agent_id: int | HumanActor,
    url: str,
) -> tuple[bytes, str] | None:
    return await capture_public_page_thumbnail(agent_id=agent_id, url=url)


async def capture_document_html_thumbnail(
    agent_id: int | HumanActor,
    reference: str,
    content: bytes,
) -> tuple[bytes, str] | None:
    return await capture_html_page_thumbnail(
        agent_id=agent_id, reference=reference, content=content,
    )


register_web_thumbnail_capture(
    capture_document_web_thumbnail, html_capture=capture_document_html_thumbnail,
)
from app.task import register_working_set_context
register_working_set_context()
from app.conversation import register_recent_conversation_document_context
register_recent_conversation_document_context()

# Mount Socket.IO as an ASGI application.
app = websocket.start(app)
