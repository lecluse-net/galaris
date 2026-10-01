"""Driver that delegates every network Harness to the common OpenAI client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID
import asyncio
from collections.abc import Callable, Awaitable

from app.agent import AgentEvent, AgentRunRequest, AgentRunCheckpoint, ExecutionResult, AIMessage
from app.agent.contracts import ResolvedExecutionTarget

from .agent_driver import OPENAI_MESSAGES_DRIVER
from .openai_client import OpenAIHarnessClient
from .service import execution_credentials, resolve_target


def _harness_id(request: AgentRunRequest) -> UUID:
    target = request.target
    if target is None or not target.target_ref.startswith("harness:"):
        raise RuntimeError("The network Harness run has no frozen Harness target.")
    try:
        return UUID(target.target_ref.removeprefix("harness:"))
    except ValueError as exc:
        raise RuntimeError("The frozen Harness target reference is invalid.") from exc


@dataclass(frozen=True)
class OpenAIMessagesDriver:
    spec = OPENAI_MESSAGES_DRIVER

    def execution_target(self, agent_id: int, configuration: Mapping[str, Any]) -> ResolvedExecutionTarget:
        return ResolvedExecutionTarget(
            provider_code=str(configuration.get("provider_code") or self.spec.code),
            target_ref=f"harness:{configuration['harness_id']}",
            revision=str(configuration.get("revision") or ""), transport="chat_completions",
            metadata={"model": str(configuration.get("model") or "")},
        )

    async def _client(self, request: AgentRunRequest) -> OpenAIHarnessClient:
        credentials = await execution_credentials(_harness_id(request))
        return OpenAIHarnessClient(
            base_url=credentials.base_url,
            token=credentials.token,
        )

    async def run(self, request: AgentRunRequest) -> ExecutionResult:
        return await self._managed_run(request)

    async def stream(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        queue: asyncio.Queue[AgentEvent | BaseException | None] = asyncio.Queue(maxsize=100)
        async def progress(message: AIMessage) -> None:
            await queue.put(AgentEvent.from_message(message))
        async def produce() -> None:
            try:
                await queue.put(AgentEvent.from_result(await self._managed_run(request, on_progress=progress)))
            except asyncio.CancelledError:
                return
            except BaseException as error:
                await queue.put(error)
            await queue.put(None)
        producer = asyncio.create_task(produce())
        try:
            while (event := await queue.get()) is not None:
                if isinstance(event, BaseException):
                    raise event
                yield event
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def _managed_run(self, request: AgentRunRequest, *, on_progress: Callable[[AIMessage], Awaitable[None]] | None = None) -> ExecutionResult:
        import hashlib
        from app.tools.facade import issue_runtime_run_grant, renew_runtime_run_grant, close_runtime_run_grant
        from core.util import get_encryption_service
        client = await self._client(request)
        await client.verify_authorization_control()
        checkpoint = request.resume_checkpoint
        resumed = checkpoint is not None and checkpoint.driver_code == self.spec.code
        if resumed and checkpoint is not None:
            credential = get_encryption_service().decrypt(str(checkpoint.data["run_context"]))
            await renew_runtime_run_grant(credential, request)
        else:
            credential = await issue_runtime_run_grant(request)
        identifier = hashlib.sha256(credential.encode()).hexdigest()
        data: dict[str, Any] = {"version": 1, "run_context": get_encryption_service().encrypt(credential),
            "cursor": checkpoint.data.get("cursor", {}) if checkpoint else {}}
        if request.save_checkpoint:
            await request.save_checkpoint(AgentRunCheckpoint(driver_code=self.spec.code, runtime_run_id=identifier,
                status="running", data=data))
        client.run_context = credential
        cursor = checkpoint.data.get("cursor") if checkpoint is not None else None
        result = await client.control_run(request.to_envelope(), runtime_run_id=identifier, start=not resumed,
            on_progress=on_progress, cursor=cast(Mapping[str, object], cursor) if isinstance(cursor, Mapping) else None)
        data["cursor"] = result.metadata["runtime_cursor"]
        if request.save_checkpoint:
            await request.save_checkpoint(AgentRunCheckpoint(driver_code=self.spec.code, runtime_run_id=identifier,
                status="waiting_for_authorization" if result.disposition == "waiting_for_authorization" else str(result.metadata["runtime_status"]),
                result=result, data=data))
        if result.disposition != "waiting_for_authorization":
            await close_runtime_run_grant(credential)
        return result

    async def cancel(self, run_id: UUID) -> None:
        await self.request_cancellation(run_id)

    async def request_cancellation(self, run_id: UUID):
        from app.agent.contracts import HarnessCancellationReceipt
        from app.tools.facade import revoke_runtime_run_grant
        grant = await revoke_runtime_run_grant(run_id)
        if grant is None:
            return HarnessCancellationReceipt(run_id=run_id, scope="remote", state="unknown")
        credentials = await execution_credentials(UUID(grant.target_ref.removeprefix("harness:")))
        client = OpenAIHarnessClient(base_url=credentials.base_url, token=credentials.token)
        confirmed = await client.cancel_control_run(grant.actor_key)
        return HarnessCancellationReceipt(run_id=run_id, scope="remote", state="confirmed" if confirmed else "requested")

    async def request_checkpoint_cancellation(self, run_id: UUID, checkpoint: AgentRunCheckpoint):
        return await self.request_cancellation(run_id)

    async def execution_configuration(self, agent: Any) -> dict[str, Any]:
        target = await resolve_target(agent)
        if target is None:
            raise RuntimeError("The network Harness driver has no selected Harness.")
        return {
            "harness_id": str(target.id),
            "provider_code": target.provider_code,
            "revision": str(target.revision),
            "base_url": target.base_url,
            "model": target.model,
            "capabilities": sorted(target.capabilities),
        }


def create_driver() -> OpenAIMessagesDriver:
    return OpenAIMessagesDriver()


__all__ = ["OpenAIMessagesDriver", "create_driver"]
