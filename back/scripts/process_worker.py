"""Run Process jobs in a supervised child with a private Unix connection to the API."""

import asyncio
from contextlib import suppress
from importlib import import_module
import socket
import sys
import time
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from core import websocket

MAX_FRAME = 1_000_000
HEARTBEAT_SECONDS = 2.0


class WorkerMessage(BaseModel):
    kind: Literal["heartbeat", "event", "reload"]
    subject: str = ""
    action: str = ""
    data: dict[str, Any] = Field(default_factory=dict[str, Any])
    room_kind: str | None = None
    resource: str | None = None


class WorkerChannel:
    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        self.lock = asyncio.Lock()

    async def send(self, message: WorkerMessage) -> None:
        frame = message.model_dump_json().encode()
        if len(frame) >= MAX_FRAME:
            logger.warning("Process worker discarded an oversized {} notification", message.kind)
            return
        async with self.lock:
            if self.writer.is_closing():
                return
            try:
                async with asyncio.timeout(3):
                    self.writer.write(frame + b"\n")
                    await self.writer.drain()
            except (OSError, TimeoutError):
                # Reconnection is a runtime restart. Durable jobs and receipts
                # are independent of notification delivery.
                self.writer.close()


class ProcessWorker:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task[None] | None = None
        self.publisher: asyncio.Task[None] | None = None
        self.channel: WorkerChannel | None = None
        self.last_heartbeat = 0.0

    def is_running(self) -> bool:
        return (self.process is not None and self.process.returncode is None
                and self.reader_task is not None and not self.reader_task.done()
                and self.last_heartbeat > 0 and time.monotonic() - self.last_heartbeat < 15)

    async def start(self) -> None:
        if self.is_running():
            return
        await self.stop()
        local, child = socket.socketpair()
        try:
            with child:
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "scripts.process_worker", str(child.fileno()),
                    pass_fds=(child.fileno(),),
                )
            reader, writer = await asyncio.open_connection(sock=local, limit=MAX_FRAME)
        except BaseException:
            local.close()
            await self.stop()
            raise
        self.channel = WorkerChannel(writer)
        ready = asyncio.Event()
        events = asyncio.Queue[WorkerMessage](maxsize=128)
        self.publisher = asyncio.create_task(self._publish(events), name="process-worker-events")
        self.reader_task = asyncio.create_task(self._read(reader, ready, events), name="process-worker-channel")
        try:
            await ready.wait()
            if not self.is_running():
                raise RuntimeError("Process worker exited before becoming ready")
        except BaseException:
            await self.stop()
            raise

    async def _read(self, reader: asyncio.StreamReader, ready: asyncio.Event,
                    events: asyncio.Queue[WorkerMessage]) -> None:
        try:
            while frame := await reader.readline():
                message = WorkerMessage.model_validate_json(frame)
                if message.kind == "heartbeat":
                    self.last_heartbeat = time.monotonic()
                    ready.set()
                elif message.kind == "event":
                    try:
                        events.put_nowait(message)
                    except asyncio.QueueFull:
                        logger.warning("Process worker notification queue is full")
        except (OSError, ValueError, ValidationError) as error:
            logger.warning("Process worker channel closed ({})", type(error).__name__)
        finally:
            self.last_heartbeat = 0.0
            ready.set()

    @staticmethod
    async def _publish(events: asyncio.Queue[WorkerMessage]) -> None:
        from app.task import scheduler

        while True:
            message = await events.get()
            if message.subject == "task":
                scheduler.wake()
            try:
                async with asyncio.timeout(5):
                    await websocket.receive_worker_event(
                        message.subject, message.action, message.data, message.room_kind, message.resource,
                    )
            except Exception as error:
                logger.warning("Process worker notification could not be delivered ({})", type(error).__name__)

    async def reload_settings(self, _name: str, _value: str | None) -> None:
        if self.channel is not None:
            await self.channel.send(WorkerMessage(kind="reload"))

    async def stop(self) -> None:
        channel, self.channel = self.channel, None
        if channel is not None:
            channel.writer.close()
        process, self.process = self.process, None
        try:
            if process is not None:
                try:
                    async with asyncio.timeout(12):
                        await process.wait()
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
        finally:
            for task in (self.reader_task, self.publisher):
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            self.reader_task = self.publisher = None
            self.last_heartbeat = 0.0


async def run_worker(fd: int) -> None:
    # The existing composition root registers the same bridges, resource
    # providers and MCP policies. Its API lifespan is owned by the parent.
    import_module("main")
    from app.agent import register_dispatcher_output_contracts
    from app.plugin.facade import restore_executable_plugins
    from app.process import ProcessEffectWorkers, configure_default_engine, register_scheduler_jobs
    from app.task import register_runtime_settings, scheduler
    from core.database import engine, get_db_session, wait_for_db
    from core.observability import configure_runtime_observability
    from core.params import params_service
    from core.util import prepare_contact_detection

    reader, writer = await asyncio.open_connection(sock=socket.socket(fileno=fd), limit=MAX_FRAME)
    channel = WorkerChannel(writer)
    effects = ProcessEffectWorkers()

    async def emit(subject: str, action: str, data: dict[str, Any], room: websocket.BaseRoom | None) -> None:
        try:
            await channel.send(WorkerMessage(kind="event", subject=subject, action=action, data=jsonable_encoder(data),
                room_kind=type(room).__name__ if room is not None else None,
                resource=str(room.resource_id) if room is not None else None))
        except (OSError, ValueError, TypeError) as error:
            logger.warning("Process worker event could not be forwarded ({})", type(error).__name__)

    async def load_settings() -> None:
        async with get_db_session():
            await params_service.load_params()
        configure_default_engine()
        register_scheduler_jobs(scheduler.register_periodic_job, scheduler.unregister_periodic_job, effects)

    async def heartbeat() -> None:
        while scheduler.is_running():
            await channel.send(WorkerMessage(kind="heartbeat"))
            await asyncio.sleep(HEARTBEAT_SECONDS)
        writer.close()

    notifications: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(25):
            await wait_for_db()
        async with get_db_session():
            await restore_executable_plugins()
        await load_settings()
        async with get_db_session():
            await configure_runtime_observability()
        register_runtime_settings()
        register_dispatcher_output_contracts()
        prepare_contact_detection()
        websocket.set_event_relay(emit)
        scheduler.start(maintenance_only=True)
        notifications = asyncio.create_task(heartbeat(), name="process-worker-heartbeat")
        logger.info("Dedicated Process worker ready")
        while frame := await reader.readline():
            if WorkerMessage.model_validate_json(frame).kind == "reload":
                await load_settings()
    finally:
        if notifications is not None:
            notifications.cancel()
            await asyncio.gather(notifications, return_exceptions=True)
        await asyncio.gather(scheduler.stop(drain_periodic=6), effects.stop())
        websocket.set_event_relay(None)
        writer.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker(int(sys.argv[1])))
