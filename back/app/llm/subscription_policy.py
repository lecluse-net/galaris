"""Identity enforcement for personal-subscription LLM providers."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

from loguru import logger
from sqlalchemy import func, select

from core.database import get_db
from core.i18n import tr
from core.user import UserModel, get_current_user_id

from .provider_models import LLMProvider


CHATGPT_CATALOG_CODE = "openai-codex"
_chatgpt_acknowledged: bool | None = None


class SubscriptionAccessError(ValueError):
    """Raised before transport when a personal subscription is not attributable."""


def update_subscription_confirmation(catalog_code: str | None, acknowledged: bool) -> None:
    """Publish committed configuration to the application-wide confirmation flag."""
    global _chatgpt_acknowledged
    if catalog_code == CHATGPT_CATALOG_CODE:
        _chatgpt_acknowledged = acknowledged is True


async def ensure_subscription_confirmation(provider: LLMProvider) -> None:
    """Check the global flag without querying SQL or caching a session/ORM object."""
    if provider.catalog_code != CHATGPT_CATALOG_CODE:
        return
    # The first caller already loaded its provider for routing/authentication. Later reads
    # use only this boolean; successful configuration writes publish changes immediately.
    if _chatgpt_acknowledged is None:
        update_subscription_confirmation(provider.catalog_code, provider.subscription_acknowledged)
    if _chatgpt_acknowledged is not True:
        raise SubscriptionAccessError(
            await tr("llm_api.errors.subscription_confirmation_required")
        )


@dataclass(frozen=True, slots=True)
class LLMExecutionAuthority:
    """Trusted authority restored by a durable background-work owner."""

    requester_user_id: int | None = None
    source_kind: str | None = None
    source_id: str | None = None
    messenger_origin: bool = False
    api_token_label: str | None = None


@dataclass(slots=True)
class _Evidence:
    user_ids: set[int]
    messenger_origin: bool = False
    messenger_user_ids: set[int] = field(default_factory=lambda: set[int]())

    def add(self, user_id: int | None) -> None:
        if user_id is not None:
            self.user_ids.add(int(user_id))

    def add_messenger(self, user_id: int | None) -> None:
        self.messenger_origin = True
        self.add(user_id)
        if user_id is not None:
            self.messenger_user_ids.add(int(user_id))


_execution_authority: ContextVar[LLMExecutionAuthority | None] = ContextVar(
    "llm_execution_authority",
    default=None,
)


def current_execution_authority() -> LLMExecutionAuthority | None:
    """Snapshot server-owned provenance before handing work to a detached executor."""
    return _execution_authority.get()


@contextmanager
def llm_execution_scope(
    *,
    requester_user_id: int | None = None,
    source_kind: str | None = None,
    source_id: str | None = None,
    messenger_origin: bool = False,
    api_token_label: str | None = None,
) -> Generator[None]:
    """Restore trusted identity provenance around deferred inference work."""

    token = _execution_authority.set(
        LLMExecutionAuthority(
            requester_user_id=requester_user_id,
            source_kind=source_kind,
            source_id=source_id,
            messenger_origin=messenger_origin,
            api_token_label=api_token_label,
        )
    )
    try:
        yield
    finally:
        _execution_authority.reset(token)


async def _message_evidence(message_id: UUID, evidence: _Evidence) -> None:
    from app.messenger import Message

    message = await get_db().get(Message, message_id)
    if message is not None and message.direction == "inbound":
        evidence.add_messenger(message.requester_user_id)
    else:
        evidence.messenger_origin = True


async def _round_evidence(round_id: UUID, evidence: _Evidence) -> None:
    from app.conversation import ConversationRound

    round_ = await get_db().get(ConversationRound, round_id)
    if round_ is not None:
        evidence.add_messenger(round_.requester_user_id)
    else:
        evidence.messenger_origin = True


async def _task_evidence(task_id: UUID, evidence: _Evidence) -> None:
    from app.conversation import ConversationTaskLink
    from app.task import Task

    pending = [task_id]
    visited: set[UUID] = set()
    while pending and len(visited) < 100:
        current_id = pending.pop()
        if current_id in visited:
            continue
        visited.add(current_id)
        task = await get_db().get(Task, current_id)
        if task is None:
            continue
        evidence.add(task.requester_user_id)
        if task.requester_user_id is None:
            evidence.add(task.created_by)
        if task.messenger_connection_id is not None or task.messenger_message_id is not None:
            evidence.messenger_origin = True
            if task.requester_user_id is not None:
                evidence.add_messenger(task.requester_user_id)
        if task.messenger_message_id is not None:
            await _message_evidence(task.messenger_message_id, evidence)
        round_id = await get_db().scalar(
            select(ConversationTaskLink.round_id).where(
                ConversationTaskLink.task_id == task.id
            )
        )
        if round_id is not None:
            await _round_evidence(round_id, evidence)
        if task.parent_id is not None:
            pending.append(task.parent_id)
        if task.source_task_id is not None:
            pending.append(task.source_task_id)


async def _process_evidence(process_run_id: UUID, evidence: _Evidence) -> None:
    from app.process import ProcessRun

    run = await get_db().get(ProcessRun, process_run_id)
    if run is None:
        return
    evidence.add(run.created_by)
    if run.task_id is not None:
        await _task_evidence(run.task_id, evidence)


async def _scope_evidence(authority: LLMExecutionAuthority, evidence: _Evidence) -> None:
    if authority.messenger_origin:
        evidence.add_messenger(authority.requester_user_id)
    else:
        evidence.add(authority.requester_user_id)
    kind = authority.source_kind
    raw_id = authority.source_id
    if kind is None or raw_id is None:
        return
    try:
        source_id = UUID(raw_id)
    except ValueError:
        return
    if kind in {"task", "task_outcome", "task_skill_learning"}:
        await _task_evidence(source_id, evidence)
    elif kind == "message":
        await _message_evidence(source_id, evidence)
    elif kind == "conversation_round":
        await _round_evidence(source_id, evidence)
    elif kind == "process_projection":
        await _process_evidence(source_id, evidence)


async def enforce_subscription_access(
    provider: LLMProvider,
    *,
    task_id: UUID | None,
    conversation_round_id: UUID | None = None,
    process_run_id: UUID | None = None,
) -> int | None:
    """Resolve and verify the requester for ChatGPT; leave other providers unchanged."""

    if provider.catalog_code != CHATGPT_CATALOG_CODE:
        return None
    await ensure_subscription_confirmation(provider)
    owner_id = provider.user_id
    if owner_id is None:
        raise SubscriptionAccessError(await tr("llm_api.errors.subscription_owner_required"))
    owner_is_active = await get_db().scalar(
        select(UserModel.is_active).where(UserModel.id == owner_id)
    )
    if owner_is_active is not True:
        raise SubscriptionAccessError(await tr("llm_api.errors.subscription_owner_invalid"))

    evidence = _Evidence(user_ids=set())
    authority = _execution_authority.get()
    if authority is not None:
        await _scope_evidence(authority, evidence)
    if task_id is not None:
        await _task_evidence(task_id, evidence)
    if conversation_round_id is not None:
        await _round_evidence(conversation_round_id, evidence)
    if process_run_id is not None:
        await _process_evidence(process_run_id, evidence)

    # An authenticated direct request is also evidence. Managed runtime requests have no user
    # context and are resolved only from their durable Task/round/process provenance.
    evidence.add(get_current_user_id())

    messenger_user_ids = evidence.messenger_user_ids
    if evidence.messenger_origin and not messenger_user_ids:
        raise SubscriptionAccessError(await tr("llm_api.errors.subscription_messenger_unlinked"))
    if evidence.messenger_origin and messenger_user_ids != {owner_id}:
        raise SubscriptionAccessError(await tr("llm_api.errors.subscription_user_mismatch"))
    if evidence.user_ids == {owner_id}:
        return owner_id
    if evidence.user_ids:
        logger.warning(
            "Denied ChatGPT subscription provider={} owner={} requesters={} messenger_origin={}",
            provider.id,
            owner_id,
            sorted(evidence.user_ids),
            evidence.messenger_origin,
        )
        raise SubscriptionAccessError(await tr("llm_api.errors.subscription_user_mismatch"))
    active_user_count = int(
        await get_db().scalar(
            select(func.count(UserModel.id)).where(UserModel.is_active.is_(True))
        )
        or 0
    )
    if active_user_count == 1:
        sole_user_id = await get_db().scalar(
            select(UserModel.id).where(UserModel.is_active.is_(True)).limit(1)
        )
        if sole_user_id == owner_id:
            return owner_id

    raise SubscriptionAccessError(await tr("llm_api.errors.subscription_requester_unknown"))


__all__ = [
    "CHATGPT_CATALOG_CODE",
    "LLMExecutionAuthority",
    "SubscriptionAccessError",
    "enforce_subscription_access",
    "llm_execution_scope",
]
