"""Stable cross-domain operations exposed by the LLM domain."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypedDict
from fastapi.responses import JSONResponse, StreamingResponse
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from contextlib import AbstractContextManager
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, JsonValue
from .accounting_scope import llm_call_accounting

from . import llm_call_service, llm_provider_service
from .provider_facade import (
    ManagedRuntimeCredential,
    ProviderQuota,
    ProviderQuotaWindow,
    managed_runtime_authentication_for,
)
from .resource_discovery import provider_connection
from .subscription_policy import ensure_subscription_confirmation
from .media_transport import GenerationProvider, media_http, media_json
from .media_facade import SelectedMediaResource, start_media_call, finish_media_call
from .media_contracts import MediaRequestRejected
from .capabilities import AICapability, with_capability
from .handlers import LLMModelInfo
from .provider_catalog import ProviderProfile
from .provider_facade import (
    ProviderResponsesPolicy,
    register_image_generation_provider,
    register_model_metadata,
    register_openai_protocol_adapter,
    register_provider,
    register_resource_discovery,
    register_responses_policy,
)

if TYPE_CHECKING:
    from app.agent.contracts import AIResult
from .contracts import InferenceEvent, InferenceRequest, TextInferenceRequest, StructuredOutputSpec, InferenceRead, InferenceCommand, InferenceAction, InferenceRunEvent, DecisionInferenceRequest
from .decision_contracts import ChoiceQuestion, DecisionResult, DecisionUnavailable, ProviderDecisionResponse
from .provider_facade import ProviderConnection, ProviderAuthenticationError, register_decision_provider
from .inference_execution import run_decision
from .profile_decisions import run_profile_decision, use_decision_models


async def proxy_chat_completion(body: dict[str, Any], **options: Any) -> JSONResponse | StreamingResponse:
    from .protocol_inference import proxy_chat_completion as proxy
    return await proxy(body, **options)


async def start_inference(request: InferenceRequest, *, inference_id: UUID | None = None) -> UUID:
    from .inference_execution import submit
    return await submit(request, inference_id=inference_id)


async def read_inference(inference_id: UUID) -> InferenceRead:
    from .inference_execution import read
    return await read(inference_id)


async def control_inference(inference_id: UUID, action: InferenceAction, *, command_id: UUID | None = None) -> InferenceCommand:
    from .inference_execution import command
    return await command(inference_id, action, command_id or uuid4())


async def stream_inference(inference_id: UUID, *, attempt_id: UUID | None = None,
                           after_sequence: int = 0) -> AsyncIterator[InferenceRunEvent]:
    from .inference_execution import events
    async for event in events(inference_id, attempt_id=attempt_id, after_sequence=after_sequence):
        yield event


async def start_inference_worker() -> None:
    from .inference_execution import start
    await start()


async def stop_inference_worker() -> None:
    from .inference_execution import stop
    await stop()


def inference_worker_running() -> bool:
    from .inference_execution import is_running
    return is_running()


def record_text_inferences(*, durable: bool = False) -> AbstractContextManager[None]:
    """Enable the journal for an existing text consumer without changing its API."""
    from .inference_facade import record_text_inferences as record

    return record(durable=durable)


def register_inference_output[T: BaseModel](
    key: str, output_type: type[T], *, validator: Callable[[T], T] | None = None,
    validator_factory: Callable[[dict[str, JsonValue]], Callable[[T], T]] | None = None,
) -> None:
    from .output_registry import register

    register(key, output_type, validator=validator, validator_factory=validator_factory)


def inference_output_spec(
    key: str, *, mode: Literal["tool", "prompted"] = "tool",
    context: dict[str, JsonValue] | None = None,
) -> StructuredOutputSpec:
    from .output_registry import specification

    return specification(key, mode=mode, context=context)


def record_structured_inferences() -> AbstractContextManager[None]:
    from .inference_facade import record_structured_inferences as record

    return record()


async def run_text_inference(
    request: TextInferenceRequest, *,
    on_event: Callable[[InferenceEvent], Awaitable[None]] | None = None,
) -> AIResult:
    from .inference_facade import run_text_inference as run

    return await run(request, on_event=on_event)


async def read_inference_events(
    call_id: UUID, *, after_sequence: int = 0, limit: int = 500,
    agent_ids: Collection[int] | None = None,
) -> list[InferenceEvent]:
    from .inference_facade import read_inference_events as read

    return await read(call_id, after_sequence=after_sequence, limit=limit, agent_ids=agent_ids)


async def read_inference_result(
    call_id: UUID, *, agent_ids: Collection[int] | None = None,
) -> AIResult | None:
    from .inference_facade import read_inference_result as read

    return await read(call_id, agent_ids=agent_ids)


class AgentRunUsage(TypedDict):
    """Gateway accounting for every persisted model call in one agent run."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    requests: int
    tool_calls: int
    cost: float
    inference_cost: float
    token_quality: Literal["exact", "estimated", "partial", "unknown"]
    cost_quality: Literal["exact", "estimated", "partial", "unknown"]


class LLMProcessingTiming(BaseModel):
    call_id: UUID
    purpose: str | None
    started_at: datetime
    completed_at: datetime | None
    seconds: float


async def task_processing_timings(task_ids: tuple[UUID, ...]) -> dict[UUID, list[LLMProcessingTiming]]:
    """Recover actual provider intervals, never transaction timestamps or prompts.

    Historical objective calls predate their Task. Attribute them only when the
    round has exactly one linked Task, so multiple admissions cannot be confused.
    """
    from sqlalchemy import func, select
    from core.database import get_db
    from app.conversation import ConversationTaskLink
    from .models import LLMCall
    from .purposes import LLMCallPurpose

    result: dict[UUID, list[LLMProcessingTiming]] = {task_id: [] for task_id in task_ids}
    columns = (LLMCall.id, LLMCall.purpose, LLMCall.started_at, LLMCall.completed_at, LLMCall.duration)
    calls = (await get_db().execute(select(LLMCall.task_id, *columns)
             .where(LLMCall.task_id.in_(task_ids)).order_by(LLMCall.started_at))).all()
    candidate_rounds = select(ConversationTaskLink.round_id).where(ConversationTaskLink.task_id.in_(task_ids))
    unique_rounds = (select(ConversationTaskLink.round_id)
                     .where(ConversationTaskLink.round_id.in_(candidate_rounds))
                     .group_by(ConversationTaskLink.round_id)
                     .having(func.count(func.distinct(ConversationTaskLink.task_id)) == 1))
    preparations = (await get_db().execute(
        select(ConversationTaskLink.task_id, *columns)
        .join(LLMCall, LLMCall.conversation_round_id == ConversationTaskLink.round_id)
        .where(ConversationTaskLink.task_id.in_(task_ids),
               ConversationTaskLink.round_id.in_(unique_rounds),
               LLMCall.task_id.is_(None),
               LLMCall.purpose == LLMCallPurpose.CONVERSATION_TASK_OBJECTIVE.value)
        .distinct()
    )).all()
    for task_id, call_id, purpose, started, completed, duration in (*calls, *preparations):
        result[task_id].append(LLMProcessingTiming(call_id=call_id, purpose=purpose,
            started_at=started, completed_at=completed, seconds=max(0.0, float(duration))))
    for intervals in result.values():
        intervals.sort(key=lambda interval: interval.started_at)
    return result


async def aggregate_task_lineage_usage(task_ids: tuple[UUID, ...]) -> tuple[int, float]:
    """Read accounting once per call, without loading prompts or counting parent totals twice."""
    from sqlalchemy import func, select
    from core.database import get_db
    from .models import LLMCall

    row = (await get_db().execute(select(
        func.coalesce(func.sum(LLMCall.total_tokens), 0),
        func.coalesce(func.sum(LLMCall.cost), 0.0),
    ).where(LLMCall.task_id.in_(task_ids)))).one()
    return max(0, int(row[0])), max(0.0, float(row[1]))


async def aggregate_agent_run_usage(
    agent_run_id: UUID,
    *,
    agent_id: int | None = None,
) -> AgentRunUsage:
    """Aggregate the authoritative ``LLMCall`` accounting for one logical run.

    The optional agent guard is used by managed-runtime HTTP consumers. Internal
    Harness drivers pass the frozen agent identity from their run envelope.
    """

    calls = await llm_call_service.list_calls(agent_run_id=agent_run_id, limit=10_000)
    if agent_id is not None and any(call.agent_id != agent_id for call in calls):
        raise PermissionError("The agent run belongs to another runtime.")
    completed = bool(calls) and all(
        str(call.status or "").lower() == "completed" for call in calls
    )
    billable_estimated = any(
        bool(call.cost_estimated) and not bool(call.is_subscription)
        for call in calls
    )
    return {
        "input_tokens": sum(max(0, int(call.input_tokens or 0)) for call in calls),
        "output_tokens": sum(max(0, int(call.output_tokens or 0)) for call in calls),
        "cache_read_tokens": sum(
            max(0, int(call.cache_read_tokens or 0)) for call in calls
        ),
        "cache_write_tokens": sum(
            max(0, int(call.cache_write_tokens or 0)) for call in calls
        ),
        "reasoning_tokens": sum(
            max(0, int(call.reasoning_tokens or 0)) for call in calls
        ),
        "requests": len(calls),
        "tool_calls": sum(len(call.tool_calls or []) for call in calls),
        "cost": sum(max(0.0, float(call.cost or 0.0)) for call in calls),
        "inference_cost": sum(
            max(0.0, float(call.inference_cost or 0.0)) for call in calls
        ),
        "token_quality": (
            "exact" if completed else "partial" if calls else "unknown"
        ),
        "cost_quality": (
            "estimated" if billable_estimated else "exact" if calls else "unknown"
        ),
    }


async def get_managed_runtime_credential(
    catalog_code: str,
) -> ManagedRuntimeCredential:
    """Resolve a fresh secret from one configured catalog provider.

    Refresh-token ownership remains in the provider bridge. Callers receive only
    the short-lived credential required by their isolated runtime.
    """

    provider = await llm_provider_service.get_provider_by_catalog_code(catalog_code)
    if provider is None:
        raise LookupError(
            f"The {catalog_code!r} provider is not configured in Galaris."
        )
    if not provider.is_active:
        raise RuntimeError(f"The {provider.name!r} provider is inactive.")
    await ensure_subscription_confirmation(provider)
    connection = provider_connection(
        provider,
        llm_provider_service.decrypt_api_key(provider.api_key),
    )
    authentication = managed_runtime_authentication_for(connection)
    if authentication is None:
        raise RuntimeError(
            f"The {provider.name!r} provider cannot authenticate a managed runtime."
        )
    return await authentication.get_runtime_credential(provider.id)


__all__ = [
    "ProviderQuota", "ProviderQuotaWindow",
    "ChoiceQuestion", "DecisionResult", "DecisionInferenceRequest", "run_decision", "run_profile_decision", "use_decision_models",
    "DecisionUnavailable", "ProviderDecisionResponse", "ProviderConnection",
    "ProviderAuthenticationError", "register_decision_provider",
    "register_inference_output", "inference_output_spec", "record_structured_inferences",
    "start_inference", "read_inference", "control_inference", "stream_inference",
    "start_inference_worker", "stop_inference_worker", "inference_worker_running",
    "record_text_inferences", "run_text_inference", "read_inference_events", "read_inference_result",
    "LLMProcessingTiming", "task_processing_timings",
    "llm_call_accounting",
    "ProviderResponsesPolicy", "register_image_generation_provider", "register_model_metadata",
    "register_openai_protocol_adapter", "register_responses_policy",
    "AICapability", "with_capability", "LLMModelInfo", "ProviderProfile", "register_provider", "register_resource_discovery",
    "GenerationProvider", "media_http", "media_json", "SelectedMediaResource", "start_media_call", "finish_media_call", "MediaRequestRejected",
    "AgentRunUsage",
    "aggregate_agent_run_usage",
    "get_managed_runtime_credential",
]
