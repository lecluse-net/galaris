"""Durable, single-use authorization before dispatch, shared by MCP and runtimes."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from contextlib import contextmanager, asynccontextmanager
from contextvars import ContextVar
from collections.abc import Generator, AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast, TYPE_CHECKING
from uuid import UUID, uuid4
from urllib.parse import urlsplit, urlunsplit

from pydantic_core import to_jsonable_python
from sqlalchemy import func, select

from app.agent import authorization_policy
from core import settings
from core.database import get_db, get_db_session
from core.util import get_encryption_service

from .authorization_models import ActionAuthorization, RuntimeRunGrant
from .contracts import ToolCallRejectedError
from . import authorization_metrics as metrics

AUTHORIZATION_META_KEY = "galaris.authorization/v1"
UNSETTLED = ("pending", "approved", "executing", "outcome_unknown")

if TYPE_CHECKING:
    from .schemas import Tool


def redacted_action_arguments(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): "[redacted]" if any(part in str(key).lower() for part in (
            "password", "secret", "token", "credential", "api_key", "authorization", "headers", "mime_bytes", "base64",
        )) else redacted_action_arguments(item) for key, item in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [redacted_action_arguments(item) for item in cast(list[Any], value)]
    if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(value)
            # Query strings, fragments and URL userinfo may contain bearer credentials.
            authority = parsed.netloc.rsplit("@", 1)[-1]
            return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))
        except ValueError:
            return "[redacted URL]"
    return value


def _action_preview(action: AuthorizationAction, policy_source: str) -> str:
    # The private full payload stays encrypted. Public summaries retain only targets.
    targets = {key: value for key, value in action.arguments.items() if key.endswith(("_id", "_uri", "_ref"))
        or key in {"uri", "url", "path", "session_id", "to", "recipients", "destination"}}
    summary = json.dumps(redacted_action_arguments(targets), ensure_ascii=False, default=str)
    return f"{action.preview[:500] or action.name}\n{action.source}/{action.kind}: {action.name}\n{policy_source}\n{summary[:2800]}"
_authorization_wakers: dict[str, Callable[[int, str], Awaitable[bool]]] = {}
_context_guards: dict[str, Callable[[int, str], Awaitable[dict[str, Any] | None]]] = {}
_dispatch_guards: dict[str, Callable[[int, str], Awaitable[bool]]] = {}
_deferred_guards: dict[str, Callable[[int, str], Awaitable[dict[str, Any] | None]]] = {}
_continued_permit: ContextVar[UUID | None] = ContextVar("continued_action_permit", default=None)


def register_deferred_authorization_guard(prefix: str, callback: Callable[[int, str], Awaitable[dict[str, Any] | None]]) -> None:
    _deferred_guards[prefix] = callback


async def _deferred_snapshot(agent_id: int, context_key: str) -> dict[str, Any] | None:
    callback = _deferred_guards.get(context_key.split(":", 1)[0])
    if callback is None:
        return await authorization_context_snapshot(agent_id, context_key)
    return await callback(agent_id, context_key)


def tool_authorization_configuration(tool: Tool) -> dict[str, Any]:
    """Bind execution settings, without invalidating an agreement on a label edit."""
    return tool.model_dump(mode="json", exclude={
        "label", "description", "created_at", "updated_at", "can_edit", "has_mcp",
        "has_file_share", "has_messenger", "has_listener",
    })


class AuthorizationSuspended(Exception):
    """An existing agreement remains valid, but its human-paused scope cannot dispatch."""


def register_authorization_dispatch_guard(prefix: str, callback: Callable[[int, str], Awaitable[bool]]) -> None:
    _dispatch_guards[prefix] = callback


async def _dispatch_available(agent_id: int, context_key: str) -> bool:
    callback = _dispatch_guards.get(context_key.split(":", 1)[0])
    return await callback(agent_id, context_key) if callback else True


def register_authorization_context_guard(prefix: str, callback: Callable[[int, str], Awaitable[dict[str, Any] | None]]) -> None:
    _context_guards[prefix] = callback


async def authorization_context_snapshot(agent_id: int, context_key: str) -> dict[str, Any]:
    for prefix, callback in _context_guards.items():
        if context_key.startswith(prefix + ":"):
            value = await callback(agent_id, context_key)
            if value is None:
                raise ToolCallRejectedError("The action context was stopped, paused, superseded or changed")
            return value
    if not context_key.startswith("principal:"):
        raise ToolCallRejectedError("The action context has no lifecycle guard")
    return {}


def register_authorization_waker(name: str, callback: Callable[[int, str], Awaitable[bool]]) -> None:
    _authorization_wakers[name] = callback


async def wake_authorization_context(agent_id: int, context_key: str) -> bool:
    for callback in _authorization_wakers.values():
        if await callback(agent_id, context_key):
            return True
    # Stateless clients resume explicitly with their opaque continuation.
    return context_key.startswith("principal:")


async def authorization_context_pending(agent_id: int, context_key: str) -> bool:
    async with get_db_session() as db:
        return bool(await db.scalar(select(ActionAuthorization.id).where(
            ActionAuthorization.agent_id == agent_id, ActionAuthorization.context_key == context_key,
            ActionAuthorization.status == "pending", ActionAuthorization.expires_at > datetime.now(timezone.utc),
        ).limit(1)))


async def invalidate_authorization_context(agent_id: int, context_key: str) -> None:
    from sqlalchemy import update
    async with get_db_session() as db:
        await db.execute(update(ActionAuthorization).where(ActionAuthorization.agent_id == agent_id,
            ActionAuthorization.context_key == context_key, ActionAuthorization.status.in_(("pending", "approved")))
            .values(status="invalidated", encrypted_arguments=None, notification_due_at=None,
                wake_due_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc)))
        await db.commit()


@dataclass(frozen=True)
class AuthorizationAction:
    agent_id: int
    runtime: str
    context_key: str
    callback_key: str
    name: str
    arguments: dict[str, Any]
    configuration: dict[str, Any]
    source: Literal["mcp", "runtime", "domain"] = "mcp"
    kind: Literal["tool", "resource", "prompt"] = "tool"
    tool_id: int | None = None
    connection_id: int | None = None
    approver_user_id: int | None = None
    preview: str = ""
    continuation: str | None = None
    allow_yolo: bool = True
    policy_name: str | None = None
    runtime_grant_id: UUID | None = None


class AuthorizationRequired(ToolCallRejectedError):
    def __init__(self, request_id: UUID, continuation: str | None = None) -> None:
        self.request_id = request_id
        self.continuation = continuation
        super().__init__("Authorization is required before this action can execute")


class AuthorizationClosed(ToolCallRejectedError):
    def __init__(self, request_id: UUID, status: str) -> None:
        self.request_id, self.status = request_id, status
        super().__init__(f"Action authorization is {status}; the operation will not be dispatched again")


@dataclass
class PreparedAuthorization:
    action: AuthorizationAction
    request_id: UUID | None = None
    claimed: bool = False


_prepared_authorization: ContextVar[PreparedAuthorization | None] = ContextVar("prepared_authorization", default=None)
_authorized_request: ContextVar[UUID | None] = ContextVar("authorized_request", default=None)


async def current_action_covers(agent_id: int, connection_id: int, name: str) -> bool:
    """A source guard cannot treat discoverability as a consumed one-action grant."""
    identifier = _authorized_request.get()
    if identifier is None:
        return False
    row = await get_db().get(ActionAuthorization, identifier)
    return bool(row is not None and (row.status == "executing" or (
        row.status == "completed" and _continued_permit.get() == identifier and row.dispatch_expected
    )) and row.agent_id == agent_id
        and row.connection_id == connection_id and row.capability_name == name
        and row.capability_kind == "tool")


@contextmanager
def authorized_request(identifier: UUID | None) -> Generator[None]:
    token = _authorized_request.set(identifier)
    try:
        yield
    finally:
        _authorized_request.reset(token)


async def register_deferred_dispatch(payload: object) -> UUID | None:
    identifier = _authorized_request.get()
    if identifier is None:
        return None
    async with get_db_session() as db:
        row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == identifier).with_for_update())
        if row is None or row.status != "executing" or row.dispatch_expected:
            raise ToolCallRejectedError("An authorization may prepare only one deferred dispatch")
        row.dispatch_expected = True
        row.deferred_payload_fingerprint = fingerprint(payload)
        await db.commit()
    return identifier


async def claim_deferred_dispatch(identifier: UUID, *, agent_id: int, payload: object, continuation: bool = False) -> None:
    """Revalidate and consume the worker permit immediately before the external start."""
    from app.connection import facade as connections
    from .tool_service import get_tool_by_id
    from .mcp_loader import load_mcp_tools
    from core.user import UserModel
    async with get_db_session() as db:
        policy = await authorization_policy(agent_id, lock=True)
        row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == identifier,
            ActionAuthorization.agent_id == agent_id).with_for_update().execution_options(populate_existing=True))
        if row is None or row.status not in (("executing", "completed") if continuation else ("executing",)) or not row.dispatch_expected or (
            (row.dispatch_claimed_at is not None) != continuation
        ):
            raise AuthorizationClosed(identifier, "outcome_unknown")
        valid = row.expires_at > datetime.now(timezone.utc) and row.deferred_payload_fingerprint == fingerprint(payload)
        if row.decision_source == "agent_yolo":
            valid = valid and policy.yolo and row.policy_version == policy.version
        valid = valid and row.approver_user_id == policy.manager_user_id
        responsible = await db.get(UserModel, row.approver_user_id, populate_existing=True)
        valid = valid and responsible is not None and responsible.is_active
        connection = await connections.get_connection(row.connection_id) if row.connection_id is not None else None
        tool = await get_tool_by_id(row.tool_id) if row.tool_id is not None else None
        definition = next((item for item in load_mcp_tools() if item.name == row.capability_name), None)
        if connection is None or not connection.active or connection.agent_id != agent_id or tool is None or definition is None:
            valid = False
        else:
            mode = await connections.resolve_function(connection, row.capability_name)
            _, params = await connections.get_params_as_dict(connection.id)
            valid = valid and mode["effective_state"] == row.mode and mode["policy_source"] == row.policy_source
            context = await _deferred_snapshot(agent_id, row.context_key)
            valid = valid and context is not None and fingerprint({"tool": tool_authorization_configuration(tool), "params": params,
                "classification": definition.approval, "reason": definition.approval_reason,
                "context_snapshot": context,
                "runtime_grant": row.runtime_grant_ref}) == row.configuration_fingerprint
        if not valid:
            if row.status == "executing":
                row.status = "invalidated"
                row.encrypted_arguments = None
                row.finished_at = datetime.now(timezone.utc)
            await db.commit()
            raise AuthorizationClosed(identifier, "invalidated")
        if not await _dispatch_available(agent_id, row.context_key):
            raise AuthorizationSuspended()
        if continuation:
            return
        row.dispatch_claimed_at = datetime.now(timezone.utc)
        await db.commit()


async def release_buffered_dispatch(identifier: UUID) -> None:
    """Only an engine's explicit no-effect admission deferral may release its reservation."""
    async with get_db_session() as db:
        row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == identifier).with_for_update())
        if row is not None and row.status == "executing" and row.dispatch_expected:
            row.dispatch_claimed_at = None
            await db.commit()


@asynccontextmanager
async def continued_deferred_dispatch(identifier: UUID | None, *, agent_id: int, payload: object) -> AsyncGenerator[None]:
    if identifier is not None:
        await claim_deferred_dispatch(identifier, agent_id=agent_id, payload=payload, continuation=True)
    token = _continued_permit.set(identifier)
    try:
        with authorized_request(identifier):
            yield
    finally:
        _continued_permit.reset(token)


def current_prepared_authorization() -> PreparedAuthorization | None:
    return _prepared_authorization.get()


@contextmanager
def prepared_authorization(action: AuthorizationAction) -> Generator[PreparedAuthorization]:
    state = PreparedAuthorization(action)
    token = _prepared_authorization.set(state)
    try:
        yield state
    finally:
        _prepared_authorization.reset(token)


async def claim_prepared_action(*, snapshot: dict[str, Any], approver_user_id: int | None = None,
                                allow_yolo: bool = True) -> UUID | None:
    state = current_prepared_authorization()
    if state is None:
        raise ToolCallRejectedError("No trusted authorization context for this prepared action")
    state.request_id = await claim_action(replace(state.action, arguments={**state.action.arguments, "prepared": snapshot},
        source="domain" if approver_user_id is not None else state.action.source,
        approver_user_id=approver_user_id, allow_yolo=allow_yolo))
    state.claimed = True
    return state.request_id


def canonical(value: object) -> str:
    return json.dumps(to_jsonable_python(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fingerprint(value: object) -> str:
    return hmac.new(str(settings.ENCRYPTION_MASTER_KEY).encode(),
                    ("galaris-action-v1:" + canonical(value)).encode(), hashlib.sha256).hexdigest()


def restore_prepared_callback(action: AuthorizationAction) -> str:
    """Restore server identity before preparation; claim_action still checks the full snapshot."""
    if not action.continuation:
        return action.callback_key
    try:
        payload = json.loads(get_encryption_service().decrypt(action.continuation))
        expected = fingerprint((action.agent_id, action.runtime, action.context_key, action.kind, action.name, action.connection_id))
        if payload["identity"] != expected or datetime.fromisoformat(payload["expires_at"]) <= datetime.now(timezone.utc):
            raise ValueError("The prepared continuation changed")
        return str(UUID(payload["callback_key"]))
    except Exception as error:
        raise ToolCallRejectedError("The prepared continuation is invalid or expired") from error


async def resolve_action_mode(action: AuthorizationAction, *, lock: bool = True) -> tuple[str, str]:
    context = await authorization_context_snapshot(action.agent_id, action.context_key)
    if "context_snapshot" in action.configuration and action.configuration["context_snapshot"] != context:
        raise ToolCallRejectedError("The action objective or context changed")
    if action.runtime_grant_id is not None:
        query = select(RuntimeRunGrant).where(RuntimeRunGrant.id == action.runtime_grant_id).execution_options(populate_existing=True)
        grant = await get_db().scalar(query.with_for_update() if lock else query)
        from .runtime_principals import runtime_principal_port
        principal = await runtime_principal_port().by_key(grant.token_id) if grant else None
        if grant is None or not grant.active or grant.agent_id != action.agent_id or grant.context_key != action.context_key or (
            grant.expires_at <= datetime.now(timezone.utc) or principal is None or not principal.enabled
        ):
            raise ToolCallRejectedError("The runtime run authority was revoked")
        from .runtime_authorization import runtime_grant_snapshot
        if grant.context_fingerprint != fingerprint(await runtime_grant_snapshot(action.agent_id, grant.runtime, action.context_key)):
            raise ToolCallRejectedError("The runtime objective changed")
        from app.agent import get_agent_record, configured_harness_selection
        agent = await get_agent_record(action.agent_id)
        target = await configured_harness_selection(agent) if agent else None
        if target is None or target.status != "ready" or target.metadata.get("authorization_enabled") is not True or grant.target_ref != f"harness:{target.id}" or grant.target_revision != str(target.revision):
            raise ToolCallRejectedError("The runtime target changed")
    if action.source != "mcp" and action.connection_id is None:
        return "ask", "software"
    from app.connection import facade as connections
    if action.connection_id is None:
        raise PermissionError("An MCP action requires a live connection")
    connection = await connections.get_connection(action.connection_id)
    if connection is None or not connection.active or connection.agent_id != action.agent_id or connection.tool_id != action.tool_id:
        raise PermissionError("Connection revoked or changed")
    policy = await connections.resolve_function(connection, action.name, capability_kind=action.kind)
    if action.kind == "resource" and action.policy_name and action.policy_name != action.name:
        inherited = await connections.resolve_function(connection, action.policy_name, capability_kind="resource")
        if inherited["effective_state"] == "disabled" or policy["state_source"] == "external_default":
            policy = inherited
    return str(policy["effective_state"]), str(policy["policy_source"])


async def _remember_configuration_fingerprint(action: AuthorizationAction) -> str | None:
    """A permanent choice belongs to the connection configuration that asked the question."""
    if action.source != "mcp" or action.connection_id is None or action.tool_id is None:
        return None
    from app.connection import facade as connections
    from .tool_service import get_tool_by_id
    from .mcp_loader import load_mcp_tools, native_tool_codes_for_tool
    connection = await connections.get_connection(action.connection_id)
    tool = await get_tool_by_id(action.tool_id)
    if connection is None or tool is None or connection.tool_id != action.tool_id:
        return None
    _, params = await connections.get_params_as_dict(connection.id)
    codes = native_tool_codes_for_tool(tool)
    definition = next((item for item in load_mcp_tools()
        if item.name == action.name and item.tool_code in codes), None)
    # Initial calls use the exact snapshot that prepared the question, including
    # a change racing with its creation. Human review reconstructs a live action
    # without configuration and compares against that original fingerprint.
    return fingerprint({"tool": action.configuration.get("tool", tool_authorization_configuration(tool)),
        "params": action.configuration.get("params", params),
        "context": action.configuration.get("context_snapshot",
            await authorization_context_snapshot(action.agent_id, action.context_key)),
        "classification": action.configuration.get("classification", definition.approval if definition else None),
        "reason": action.configuration.get("reason", definition.approval_reason if definition else None)})


async def claim_action(action: AuthorizationAction) -> UUID | None:
    """Commit a one-use claim. Pending calls raise a control signal without keeping a session."""
    if not action.name or len(action.name.encode("utf-8")) > (2000 if action.kind == "resource" else 255):
        raise ToolCallRejectedError("Invalid bounded action identity")
    async with get_db_session():
        context = await authorization_context_snapshot(action.agent_id, action.context_key)
    action = replace(action, configuration={**action.configuration, "context_snapshot": context,
        "runtime_grant": str(action.runtime_grant_id) if action.runtime_grant_id else None})
    serialized = canonical(action.arguments)
    if len(serialized.encode()) > 1024 * 1024:
        raise ToolCallRejectedError("Authorization arguments exceed the bounded snapshot limit")
    callback_key = action.callback_key
    continuation_request: UUID | None = None
    if action.continuation:
        try:
            payload = json.loads(get_encryption_service().decrypt(action.continuation))
            if (payload["binding"] != fingerprint((action.agent_id, action.runtime, action.context_key,
                    action.source, action.kind, action.name, action.connection_id, action.arguments))
                    or datetime.fromisoformat(payload["expires_at"]) <= datetime.now(timezone.utc)):
                raise ValueError("Invalid authorization continuation")
            callback_key = payload["callback_key"]
            continuation_request = UUID(payload["request_id"])
        except Exception as exc:
            raise ToolCallRejectedError("Authorization continuation is invalid or expired") from exc
    operation_key = fingerprint((action.agent_id, action.runtime, action.context_key,
                                 callback_key, action.source, action.kind, action.name,
                                 action.connection_id))
    arguments_fingerprint = fingerprint(action.arguments)
    configuration_fingerprint = fingerprint(action.configuration)
    now = datetime.now(timezone.utc)
    pending: UUID | None = None
    closed: tuple[UUID, str] | None = None
    claimed: UUID | None = None
    async with get_db_session():
        db = get_db()
        policy = await authorization_policy(action.agent_id, lock=True)
        approver = action.approver_user_id or policy.manager_user_id
        mode, origin = await resolve_action_mode(action)
        if mode == "disabled":
            raise ToolCallRejectedError("The capability is disabled")
        # Serialize quota and identity changes consistently: agent, human, operation.
        from core.user import UserModel
        responsible = await db.scalar(select(UserModel).where(UserModel.id == approver).with_for_update()
            .execution_options(populate_existing=True))
        if responsible is None or not responsible.is_active:
            raise ToolCallRejectedError("An active human approver is required")
        row = await db.scalar(select(ActionAuthorization).where(
            ActionAuthorization.operation_key == operation_key,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None:
            if continuation_request is not None:
                raise AuthorizationClosed(continuation_request, "invalidated")
            if mode == "enabled":
                return None
            refused = await db.scalar(select(ActionAuthorization.id).where(
                ActionAuthorization.agent_id == action.agent_id,
                ActionAuthorization.context_key == action.context_key,
                ActionAuthorization.capability_name == action.name,
                ActionAuthorization.fingerprint == arguments_fingerprint,
                ActionAuthorization.configuration_fingerprint == configuration_fingerprint,
                ActionAuthorization.policy_version == policy.version,
                ActionAuthorization.mode == mode, ActionAuthorization.policy_source == origin,
                ActionAuthorization.status == "denied", ActionAuthorization.expires_at > now,
            ).limit(1))
            if refused is not None:
                raise AuthorizationClosed(refused, "denied")
            # Serialize the responsible user's quota across all of their agents.
            agent_count = await db.scalar(select(func.count()).select_from(ActionAuthorization).where(
                ActionAuthorization.agent_id == action.agent_id, ActionAuthorization.status.in_(UNSETTLED)))
            manager_count = await db.scalar(select(func.count()).select_from(ActionAuthorization).where(
                ActionAuthorization.approver_user_id == approver, ActionAuthorization.status.in_(UNSETTLED)))
            if int(agent_count or 0) >= 50 or int(manager_count or 0) >= 200:
                raise ToolCallRejectedError("Too many unresolved authorization requests")
            row = ActionAuthorization(
                id=uuid4(), operation_key=operation_key, agent_id=action.agent_id,
                runtime_grant_id=action.runtime_grant_id,
                runtime_grant_ref=str(action.runtime_grant_id) if action.runtime_grant_id else None,
                approver_user_id=approver, tool_id=action.tool_id, connection_id=action.connection_id,
                source=action.source, capability_kind=action.kind, capability_name=action.name,
                policy_name=action.policy_name,
                runtime=action.runtime, context_key=action.context_key,
                fingerprint=arguments_fingerprint, configuration_fingerprint=configuration_fingerprint,
                remember_configuration_fingerprint=await _remember_configuration_fingerprint(action),
                mode=mode, policy_source=origin, policy_version=policy.version,
                preview=_action_preview(action, origin),
                encrypted_arguments=get_encryption_service().encrypt(serialized),
                expires_at=now + timedelta(hours=24), notification_due_at=now,
                status="approved" if policy.yolo and action.allow_yolo else "pending",
                decision_source="agent_yolo" if policy.yolo and action.allow_yolo else None,
                decided_at=now if policy.yolo and action.allow_yolo else None,
            )
            db.add(row)
            await db.flush()
            metrics.transition(row.status, row.decision_source or "human_required")
        if row.status in ("pending", "approved"):
            if row.expires_at <= now:
                row.status = "expired"
            elif (row.fingerprint != arguments_fingerprint or
                  row.configuration_fingerprint != configuration_fingerprint or
                  row.mode != mode or row.policy_source != origin or
                  row.approver_user_id != approver or
                  (row.decision_source == "agent_yolo" and
                   (not policy.yolo or row.policy_version != policy.version))):
                row.status = "invalidated"
        if row.fingerprint != arguments_fingerprint or row.configuration_fingerprint != configuration_fingerprint:
            closed = (row.id, "invalidated")
        elif row.status == "pending":
            # Enabling YOLO later never answers an already pending human question.
            pending = row.id
        elif row.status == "approved":
            if not await _dispatch_available(action.agent_id, action.context_key):
                pending = row.id
            else:
                row.status = "executing"
                row.claimed_at = now
                row.notification_due_at = None
                claimed = row.id
                metrics.transition("executing", row.decision_source or "unknown")
        else:
            closed = (row.id, row.status)
        if row.status in ("expired", "invalidated"):
            row.encrypted_arguments = None
            row.notification_due_at = None
            row.finished_at = now
        await db.commit()
    if pending is not None:
        token = get_encryption_service().encrypt(canonical({
            "request_id": str(pending), "callback_key": callback_key,
            "identity": fingerprint((action.agent_id, action.runtime, action.context_key, action.kind, action.name, action.connection_id)),
            "binding": fingerprint((action.agent_id, action.runtime, action.context_key, action.source,
                action.kind, action.name, action.connection_id, action.arguments)),
            "expires_at": row.expires_at.isoformat(),
        }))
        raise AuthorizationRequired(pending, token)
    if closed is not None:
        raise AuthorizationClosed(*closed)
    return claimed


async def finish_action(request_id: UUID | None, *, receipt: object = None,
                        outcome: Literal["completed", "failed", "outcome_unknown"] = "completed",
                        deferred: bool = False) -> None:
    if request_id is None:
        return
    async with get_db_session():
        db = get_db()
        row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == request_id).with_for_update())
        if row is None or (row.status != "executing" and not (
            row.status == "outcome_unknown" and outcome in ("completed", "failed") and receipt is not None
        )):
            return
        if row.dispatch_expected and not deferred and outcome == "completed":
            return
        row.status = outcome
        metrics.transition(outcome, row.decision_source or "unknown")
        row.finished_at = datetime.now(timezone.utc)
        if outcome != "outcome_unknown":
            row.encrypted_arguments = None
        if receipt is not None:
            try:
                value = canonical(receipt)
                if len(value.encode()) <= 1024 * 1024:
                    row.encrypted_receipt = get_encryption_service().encrypt(value)
            except (TypeError, ValueError):
                pass  # The operation is still consumed; unsupported receipts cannot trigger replay.
        await db.commit()


async def can_remember_action(row: ActionAuthorization) -> bool:
    """Only a live, configurable MCP function has a reusable connection policy."""
    if (row.status != "pending" or row.expires_at <= datetime.now(timezone.utc) or row.mode != "ask"
            or row.remember_configuration_fingerprint is None
            or row.source != "mcp" or row.capability_kind != "tool" or row.connection_id is None or row.tool_id is None
            or (row.runtime_grant_ref is not None and row.runtime_grant_id is None)):
        return False
    from app.connection import facade as connections
    from .tool_service import get_tool_by_id
    connection = await connections.get_connection(row.connection_id)
    tool = await get_tool_by_id(row.tool_id)
    if (connection is None or not connection.active or connection.agent_id != row.agent_id
            or connection.tool_id != row.tool_id or tool is None):
        return False
    try:
        action = AuthorizationAction(
            agent_id=row.agent_id, runtime=row.runtime, context_key=row.context_key,
            callback_key="remember-policy", source="mcp", name=row.capability_name,
            arguments={}, configuration={}, tool_id=row.tool_id, connection_id=row.connection_id,
            runtime_grant_id=row.runtime_grant_id,
        )
        mode, source = await resolve_action_mode(action, lock=False)
        if await _remember_configuration_fingerprint(action) != row.remember_configuration_fingerprint:
            return False
    except (PermissionError, ValueError, LookupError):
        return False
    return mode == "ask" and source == row.policy_source


async def answer_action(request_id: UUID, *, user_id: int, approved: bool, remember: bool = False) -> bool:
    """First valid human transition wins; management access alone does not imply consent."""
    db = get_db()
    identity = await db.scalar(select(ActionAuthorization.agent_id).where(ActionAuthorization.id == request_id))
    if identity is None:
        return False
    try:
        policy = await authorization_policy(identity, lock=True)
    except PermissionError:
        return False
    from core.user import UserModel
    responsible = await db.scalar(select(UserModel).where(UserModel.id == user_id).with_for_update()
        .execution_options(populate_existing=True))
    if responsible is None or not responsible.is_active:
        return False
    row = await db.scalar(select(ActionAuthorization).where(ActionAuthorization.id == request_id).with_for_update()
                          .execution_options(populate_existing=True))
    if row is None or row.approver_user_id != user_id:
        return False
    # Domain approvers must also be revalidated by their domain before dispatch.
    if row.source != "domain" and row.approver_user_id != policy.manager_user_id:
        return False
    now = datetime.now(timezone.utc)
    if row.status != "pending":
        return False
    if remember:
        if not approved or row.expires_at <= now or row.tool_id is None:
            return False
        from .administration_lock import lock_tools
        from app.connection import facade as connections
        await lock_tools([row.tool_id])
        if not await can_remember_action(row):
            return False
        assert row.connection_id is not None
        await connections.set_connection_function_state(row.connection_id, row.capability_name, "enabled", commit=False)
        # Consume this operation once while future calls use its connection policy.
        row.mode = "enabled"
        row.policy_source = "connection"
    if row.expires_at <= now:
        row.status = "expired"
        row.encrypted_arguments = None
    else:
        row.status = "approved" if approved else "denied"
        row.decision_source = "human"
        row.decided_at = now
        row.wake_due_at = now
        if not approved:
            row.encrypted_arguments = None
            row.finished_at = now
    row.notification_due_at = None
    await db.commit()
    metrics.transition(row.status, "human")
    metrics.wait_seconds.record(max(0.0, (now - row.created_at).total_seconds()), {"status": row.status})
    return row.status in ("approved", "denied")


async def authorization_status(request_id: UUID, *, agent_id: int) -> str:
    """Server-side continuation query, scoped to the executing agent."""
    async with get_db_session() as db:
        row = await db.scalar(select(ActionAuthorization).where(
            ActionAuthorization.id == request_id, ActionAuthorization.agent_id == agent_id,
        ))
        if row is None:
            return "invalidated"
        if row.status in ("pending", "approved") and row.expires_at <= datetime.now(timezone.utc):
            return "expired"
        return row.status
