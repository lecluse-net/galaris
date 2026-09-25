"""Live authorization and atomic, attributable Lab command receipts."""

from collections.abc import Awaitable, Callable
from functools import wraps
import hashlib
import inspect
import json
from typing import Any, TypeVar, cast

from pydantic import BaseModel
from sqlalchemy import select, text

from app.connection import facade as connections
from app.tools import McpToolContext, RecoverableToolError, require_galaris_admin_access
from core.database import get_db

from .capture_service import CaptureParametersMismatch
from .models import LabCommand
from .mechanism_evaluation_service import RevisionConflictError
from .dispatcher_evaluation_service import RevisionConflictError as DispatcherRevisionConflictError
from .transactions import atomic_command

F = TypeVar("F", bound=Callable[..., Awaitable[dict[str, Any]]])
MAX_RESPONSE_BYTES = 1_000_000


def json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=json_value, ensure_ascii=False).encode()
    ).hexdigest()


async def authorize(ctx: McpToolContext, action: str, *, sources: bool = False) -> None:
    if not await connections.has_active_tool_function(ctx.agent_id, "lab", action):
        raise PermissionError("An active lab connection with this function enabled is required.")
    if sources:
        await require_galaris_admin_access(ctx.agent_id)
        for function in ("conversation_round_get", "voice_turn_get", "llm_call", "llm_calls"):
            if not await connections.has_active_tool_function(
                ctx.agent_id, "galaris_admin", function
            ):
                raise PermissionError(
                    "Real Lab sources require the execution-inspection functions of galaris_admin."
                )


async def has_source_access(ctx: McpToolContext) -> bool:
    try:
        await authorize(ctx, "lab_source_list", sources=True)
    except PermissionError:
        return False
    return True


def bounded(payload: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode()) > MAX_RESPONSE_BYTES:
        raise RecoverableToolError(
            "Lab response exceeds 1 MB; use pagination.summary_only=true to discover IDs, then lab_content_read for complete character pages."
        )
    return payload


def lab_call(*, mutation: bool = False, sources: bool = False) -> Callable[[F], F]:
    def decorate(function: F) -> F:
        @wraps(function)
        async def invoke(ctx: McpToolContext, *args: Any, **kwargs: Any) -> dict[str, Any]:
            await authorize(ctx, function.__name__, sources=sources)
            if not mutation:
                return bounded(await function(ctx, *args, **kwargs))
            arguments = inspect.signature(function).bind(ctx, *args, **kwargs)
            arguments.apply_defaults()
            values = dict(arguments.arguments)
            values.pop("ctx")
            key = str(values.pop("invocation_key", "")).strip()
            if not key or len(key) > 200:
                raise ValueError(
                    "Provide an invocation_key of 1–200 characters; reuse it only for this command's retries."
                )
            digest = fingerprint(values)
            lock = int.from_bytes(
                hashlib.sha256(f"lab:{ctx.agent_id}:{function.__name__}:{key}".encode()).digest()[
                    :8
                ],
                signed=True,
            )
            await get_db().execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
            receipt = await get_db().scalar(
                select(LabCommand).where(
                    LabCommand.agent_id == ctx.agent_id,
                    LabCommand.action == function.__name__,
                    LabCommand.invocation_key == key,
                )
            )
            if receipt is not None:
                if receipt.fingerprint != digest:
                    raise RevisionConflictError(
                        "The invocation_key already belongs to different arguments."
                    )
                return bounded(receipt.response)
            with atomic_command():
                try:
                    response = bounded(await function(ctx, *args, **kwargs))
                except CaptureParametersMismatch as exc:
                    # Preserve the actionable comparison/token through the common MCP error renderer.
                    detail = {
                        "code": "dataset_parameters_mismatch",
                        "confirmation_token": exc.detail["confirmation_token"],
                        "dataset_id": exc.detail["dataset_id"],
                        "differences": exc.detail["differences"],
                    }
                    raise RecoverableToolError(
                        json.dumps(detail, ensure_ascii=False, default=str)
                    ) from exc
                get_db().add(
                    LabCommand(
                        agent_id=ctx.agent_id,
                        task_id=ctx.task_id,
                        action=function.__name__,
                        invocation_key=key,
                        fingerprint=digest,
                        response=response,
                    )
                )
                await get_db().flush()
            return response

        @wraps(function)
        async def recoverable(ctx: McpToolContext, *args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return await invoke(ctx, *args, **kwargs)
            except (RevisionConflictError, DispatcherRevisionConflictError) as exc:
                raise RecoverableToolError(f"revision_conflict: {exc}") from exc
            except LookupError as exc:
                raise RecoverableToolError(f"not_found: {exc}") from exc

        return cast(F, recoverable)

    return decorate
