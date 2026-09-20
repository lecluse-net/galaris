"""Harness catalogue and single-runtime selection orchestration."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.agent import Agent, agent_has_open_tasks, get_agent_record, normalize_capabilities
from core.database import get_db, get_db_session
from core.params import params_service
from core.util import get_encryption_service

from .contracts import (
    HarnessAction,
    HarnessCapability,
    HarnessCredentials,
    HarnessLifecycleStatus,
    HarnessProvider,
    HarnessProvisioningRequest,
    HarnessTarget,
)
from .models import AgentHarness, Harness
from .registry import all_providers, get_provider
from .schemas import (
    HarnessCatalogCreate,
    HarnessCatalogRead,
    HarnessCatalogUpdate,
    HarnessProbe,
    HarnessProbeResult,
    HarnessRead,
    HarnessSelectionUpdate,
)


class HarnessConflictError(RuntimeError):
    """A Harness operation would violate selection or lifecycle invariants."""


_agent_locks: dict[int, asyncio.Lock] = {}


@dataclass(frozen=True)
class HarnessCleanup:
    """Immutable cleanup captured before a Harness preference is replaced."""

    assignment_id: UUID
    agent_id: int
    operation_id: UUID
    provider_code: str
    request: HarnessProvisioningRequest


def _agent_lock(agent_id: int) -> asyncio.Lock:
    return _agent_locks.setdefault(agent_id, asyncio.Lock())


async def _assignment_for_agent(agent_id: int) -> AgentHarness | None:
    return await get_db().scalar(
        select(AgentHarness).where(AgentHarness.agent_id == agent_id)
    )


async def _catalogue_harness(harness_id: UUID) -> Harness | None:
    return await get_db().get(Harness, harness_id)


def _bridge_catalogue_id(provider_code: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"galaris:harness-bridge:{provider_code}")


def _bridge_provider_for_id(harness_id: UUID) -> HarnessProvider | None:
    return next(
        (
            provider
            for provider in all_providers()
            if provider.enabled_param is not None
            and _bridge_catalogue_id(provider.code) == harness_id
        ),
        None,
    )


async def _bridge_enabled(provider: HarnessProvider) -> bool:
    if provider.enabled_param is None:
        return False
    value = await params_service.get_or_default(provider.enabled_param)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


async def _bridge_harness(provider: HarnessProvider) -> Harness:
    return Harness(
        id=_bridge_catalogue_id(provider.code),
        name=provider.label,
        provider_code=provider.code,
        driver_code=provider.driver_code,
        enabled=await _bridge_enabled(provider),
        revision=1,
        settings={"bridge": True},
        capabilities=sorted(normalize_capabilities(provider.capabilities())),
    )


async def _catalogue_choice(harness_id: UUID) -> Harness | None:
    provider = _bridge_provider_for_id(harness_id)
    if provider is not None:
        return await _bridge_harness(provider)
    row = await _catalogue_harness(harness_id)
    if row is None or row.provider_code != "openai_messages":
        return None
    return row


def _assignment_matches(assignment: AgentHarness, harness: Harness) -> bool:
    if harness.provider_code == "openai_messages":
        return assignment.harness_id == harness.id
    return (
        assignment.harness_id is None
        and assignment.provider_code == harness.provider_code
    )


async def _harness_for_assignment(assignment: AgentHarness) -> Harness | None:
    if assignment.harness_id is not None:
        return await _catalogue_harness(assignment.harness_id)
    try:
        provider = get_provider(assignment.provider_code)
    except LookupError:
        return None
    if provider.enabled_param is None:
        return None
    return await _bridge_harness(provider)


async def _assignments_for(
    harness: Harness,
    *,
    agent_ids: Collection[int] | None = None,
) -> list[AgentHarness]:
    query = select(AgentHarness)
    if harness.provider_code == "openai_messages":
        query = query.where(AgentHarness.harness_id == harness.id)
    else:
        query = query.where(
            AgentHarness.harness_id.is_(None),
            AgentHarness.provider_code == harness.provider_code,
        )
    if agent_ids is not None:
        query = query.where(AgentHarness.agent_id.in_(agent_ids))
    return list((await get_db().scalars(query.order_by(AgentHarness.agent_id))).all())


def _request(
    assignment: AgentHarness,
    harness: Harness,
    agent: Agent,
) -> HarnessProvisioningRequest:
    return HarnessProvisioningRequest(
        harness_id=assignment.id,
        catalogue_harness_id=harness.id,
        agent_id=assignment.agent_id,
        agent_code=agent.code,
        name=harness.name,
        base_url=harness.base_url,
        model=harness.model,
        revision=int(harness.revision or 1),
        settings=dict(harness.settings or {}),
    )


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    encryption = get_encryption_service()
    return encryption.decrypt(value) if encryption.is_encrypted(value) else value


def _encrypt(value: str | None) -> str | None:
    if not value:
        return None
    encryption = get_encryption_service()
    return value if encryption.is_encrypted(value) else encryption.encrypt(value)


def _capabilities(
    assignment: AgentHarness,
    harness: Harness,
) -> frozenset[HarnessCapability]:
    declared = normalize_capabilities(get_provider(harness.provider_code).capabilities())
    stored = normalize_capabilities(assignment.capabilities or harness.capabilities)
    management = {"status", "start", "stop", "restart", "update", "logs", "refresh"}
    # A persisted capability cannot invent support removed from the current adapter.
    return declared & (stored | management)


def _catalogue_read(harness: Harness, *, assigned_agents: int) -> HarnessCatalogRead:
    provider = get_provider(harness.provider_code)
    return HarnessCatalogRead(
        id=harness.id,
        name=harness.name,
        provider_code=harness.provider_code,
        provider_label=provider.label,
        driver_code=harness.driver_code,
        enabled=harness.enabled,
        base_url=harness.base_url,
        model=harness.model,
        token_configured=bool(harness.api_token_encrypted),
        settings=dict(harness.settings or {}),
        revision=int(harness.revision or 1),
        capabilities=sorted(normalize_capabilities(provider.capabilities())),
        containerized=provider.containerized,
        max_parallel_tasks=provider.max_parallel_tasks,
        assigned_agents=assigned_agents,
        last_error=harness.last_error,
    )


def _selection_read(
    assignment: AgentHarness,
    harness: Harness,
) -> HarnessRead:
    provider = get_provider(harness.provider_code)
    return HarnessRead(
        id=assignment.id,
        harness_id=harness.id,
        agent_id=assignment.agent_id,
        internal=False,
        name=harness.name,
        provider_code=harness.provider_code,
        driver_code=harness.driver_code,
        base_url=assignment.runtime_base_url or harness.base_url,
        model=assignment.runtime_model or harness.model,
        token_configured=bool(
            assignment.runtime_token_encrypted or harness.api_token_encrypted
        ),
        lifecycle_status=cast(HarnessLifecycleStatus, assignment.lifecycle_status),
        revision=assignment.revision,
        capabilities=sorted(_capabilities(assignment, harness)),
        containerized=provider.containerized,
        max_parallel_tasks=provider.max_parallel_tasks,
        last_error=assignment.last_error,
    )


def internal_read(agent_id: int) -> HarnessRead:
    return HarnessRead(
        agent_id=agent_id,
        internal=True,
        name="Internal Pydantic AI",
        provider_code="internal",
        driver_code="internal",
        lifecycle_status="ready",
        capabilities=[
            "execute", "streaming", "skills", "runtime_files", "mcp", "memory",
        ],
        containerized=False,
        max_parallel_tasks=None,
    )


async def list_catalogue(
    *,
    enabled_only: bool = False,
    agent_ids: Collection[int] | None = None,
) -> list[HarnessCatalogRead]:
    bridges = [
        await _bridge_harness(provider)
        for provider in all_providers()
        if provider.enabled_param is not None
    ]
    openai_rows = list(
        (
            await get_db().scalars(
                select(Harness)
                .where(Harness.provider_code == "openai_messages")
                .order_by(Harness.name)
            )
        ).all()
    )
    rows = sorted([*bridges, *openai_rows], key=lambda item: item.name.lower())
    result: list[HarnessCatalogRead] = []
    for row in rows:
        if enabled_only and not row.enabled:
            continue
        result.append(
            _catalogue_read(
                row,
                assigned_agents=len(
                    await _assignments_for(row, agent_ids=agent_ids)
                ),
            )
        )
    return result


async def get_catalogue_harness(
    harness_id: UUID,
    *,
    agent_ids: Collection[int] | None = None,
) -> HarnessCatalogRead:
    row = await _catalogue_choice(harness_id)
    if row is None:
        raise LookupError("Harness not found.")
    return _catalogue_read(
        row,
        assigned_agents=len(await _assignments_for(row, agent_ids=agent_ids)),
    )


async def _validated_catalogue_values(
    *,
    provider_code: str,
    base_url: str | None,
    token: str | None,
    model: str | None,
) -> tuple[str | None, str | None]:
    if provider_code != "openai_messages":
        return base_url, model
    from .openai_provider import validate_configuration

    result = await validate_configuration(
        base_url=base_url,
        token=token,
        model=model,
    )
    return result.base_url, result.model


async def _require_unique_name(name: str, *, excluding: UUID | None = None) -> None:
    query = select(Harness.id).where(func.lower(Harness.name) == name.lower())
    if excluding is not None:
        query = query.where(Harness.id != excluding)
    if await get_db().scalar(query) is not None:
        raise HarnessConflictError("A Harness with this name already exists.")


async def create_catalogue_harness(data: HarnessCatalogCreate) -> HarnessCatalogRead:
    if data.provider_code != "openai_messages":
        raise HarnessConflictError(
            "Only OpenAI Messages Harnesses can be added to the catalogue."
        )
    provider = get_provider(data.provider_code)
    await _require_unique_name(data.name)
    base_url, model = await _validated_catalogue_values(
        provider_code=provider.code,
        base_url=data.base_url,
        token=data.token,
        model=data.model,
    )
    row = Harness(
        name=data.name,
        provider_code=provider.code,
        driver_code=provider.driver_code,
        enabled=data.enabled,
        base_url=base_url,
        model=model,
        api_token_encrypted=_encrypt(data.token),
        settings=dict(data.settings),
        capabilities=sorted(normalize_capabilities(provider.capabilities())),
    )
    db = get_db()
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HarnessConflictError("A Harness with this name already exists.") from exc
    await db.refresh(row)
    return _catalogue_read(row, assigned_agents=0)


async def update_catalogue_harness(
    harness_id: UUID,
    data: HarnessCatalogUpdate,
) -> HarnessCatalogRead:
    bridge_provider = _bridge_provider_for_id(harness_id)
    if bridge_provider is not None:
        row = await _bridge_harness(bridge_provider)
        assignments = await _assignments_for(row)
        if not data.enabled and assignments:
            await _return_assignments_to_internal(row, assignments)
            assignments = []
        if bridge_provider.enabled_param is None:
            raise HarnessConflictError("This bridge Harness has no activation parameter.")
        if not await params_service.set(
            bridge_provider.enabled_param,
            "true" if data.enabled else "false",
        ):
            raise RuntimeError("The bridge Harness activation parameter is missing.")
        row.enabled = data.enabled
        return _catalogue_read(row, assigned_agents=len(assignments))

    row = await _catalogue_harness(harness_id)
    if row is None:
        raise LookupError("Harness not found.")
    if row.provider_code != "openai_messages":
        raise HarnessConflictError("Only OpenAI Messages configurations belong to this table.")
    db = get_db()
    assignments = await _assignments_for(row)
    provider = get_provider(row.provider_code)
    await _require_unique_name(data.name, excluding=row.id)
    configuration_changed = (
        data.base_url != row.base_url
        or data.model != row.model
        or data.token is not None
        or data.settings != {"streams_ai_messages": True, **dict(row.settings or {})}
    )
    if assignments and provider.containerized and configuration_changed:
        raise HarnessConflictError(
            "A containerized Harness cannot change while it is selected by agents."
        )
    if configuration_changed:
        for assignment in assignments:
            await _require_switchable(assignment.agent_id)
    if not data.enabled and assignments:
        await _return_assignments_to_internal(row, assignments)
        assignments = []
    row.name = data.name
    row.enabled = data.enabled
    if configuration_changed:
        effective_token = (
            data.token if data.token is not None else _decrypt(row.api_token_encrypted)
        )
        base_url, model = await _validated_catalogue_values(
            provider_code=row.provider_code,
            base_url=data.base_url,
            token=effective_token,
            model=data.model,
        )
        row.base_url = base_url
        row.model = model
        row.api_token_encrypted = _encrypt(effective_token)
        row.settings = dict(data.settings)
        row.revision = int(row.revision or 0) + 1
        row.last_error = None
        for assignment in assignments:
            assignment.revision = row.revision
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HarnessConflictError("A Harness with this name already exists.") from exc
    await db.refresh(row)
    return _catalogue_read(row, assigned_agents=len(assignments))


async def delete_catalogue_harness(harness_id: UUID) -> None:
    if _bridge_provider_for_id(harness_id) is not None:
        raise HarnessConflictError(
            "A bridge Harness cannot be deleted; disable it instead."
        )
    row = await _catalogue_harness(harness_id)
    if row is None:
        raise LookupError("Harness not found.")
    if row.provider_code != "openai_messages":
        raise HarnessConflictError("Only OpenAI Messages configurations can be deleted.")
    assignments = await _assignments_for(row)
    await _return_assignments_to_internal(row, assignments)
    row.soft_delete()
    await get_db().commit()


async def probe_openai_harness(data: HarnessProbe) -> HarnessProbeResult:
    """Test one OpenAI Messages endpoint without exposing stored credentials."""

    token = data.token
    if data.harness_id is not None:
        row = await _catalogue_harness(data.harness_id)
        if row is None:
            raise LookupError("Harness not found.")
        if row.provider_code != "openai_messages":
            raise ValueError("Only OpenAI Messages Harnesses can be tested here.")
        if token is None:
            token = _decrypt(row.api_token_encrypted)
    from .openai_provider import probe_configuration

    base_url, models = await probe_configuration(base_url=data.base_url, token=token)
    return HarnessProbeResult(base_url=base_url, models=models)


async def get_for_agent(agent_id: int) -> HarnessRead:
    agent = await get_agent_record(agent_id)
    if agent is None:
        raise LookupError("Agent not found.")
    assignment = await _assignment_for_agent(agent_id)
    if assignment is None:
        return internal_read(agent_id)
    if bool((assignment.provider_metadata or {}).get("target_internal")):
        return internal_read(agent_id)
    if assignment.harness_id is not None and assignment.harness_id != agent.task_harness_id:
        raise HarnessConflictError("The agent Harness selection is inconsistent.")
    if assignment.harness_id is None and agent.task_harness_id is not None:
        raise HarnessConflictError("The agent bridge Harness selection is inconsistent.")
    harness = await _harness_for_assignment(assignment)
    if harness is None:
        raise HarnessConflictError("The selected Harness no longer exists.")
    return _selection_read(assignment, harness)


async def resolve_target(agent: Agent) -> HarnessTarget | None:
    """Return ``None`` only for the local, container-free internal Harness."""

    assignment = await _assignment_for_agent(agent.id)
    if assignment is None:
        return None
    if bool((assignment.provider_metadata or {}).get("target_internal")):
        return None
    if assignment.harness_id is not None and assignment.harness_id != agent.task_harness_id:
        raise HarnessConflictError("The selected Harness does not exist or belongs elsewhere.")
    harness = await _harness_for_assignment(assignment)
    if harness is None:
        raise HarnessConflictError("The selected Harness configuration no longer exists.")
    return HarnessTarget(
        id=assignment.id,
        harness_id=harness.id,
        agent_id=assignment.agent_id,
        name=harness.name,
        provider_code=harness.provider_code,
        driver_code=harness.driver_code,
        base_url=assignment.runtime_base_url or harness.base_url,
        model=assignment.runtime_model or harness.model,
        revision=assignment.revision,
        status=cast(HarnessLifecycleStatus, assignment.lifecycle_status),
        max_parallel_tasks=get_provider(harness.provider_code).max_parallel_tasks,
        last_error=assignment.last_error,
        capabilities=_capabilities(assignment, harness),
        metadata={
            **{
                key: value
                for key, value in cast(Mapping[str, Any], assignment.provider_metadata or {}).items()
                if value is None or isinstance(value, (str, int, float, bool))
            },
            "streams_ai_messages": harness.provider_code != "openai_messages"
            or (harness.settings or {}).get("streams_ai_messages") is not False,
        },
    )


async def execution_credentials(harness_id: UUID) -> HarnessCredentials:
    assignment = await get_db().get(AgentHarness, harness_id)
    if assignment is None or assignment.lifecycle_status != "ready":
        raise RuntimeError("The frozen Harness target is not ready.")
    harness = await _harness_for_assignment(assignment)
    if harness is None:
        raise RuntimeError("The frozen Harness configuration no longer exists.")
    base_url = assignment.runtime_base_url or harness.base_url
    model = assignment.runtime_model or harness.model
    if not base_url or not model:
        raise RuntimeError("The frozen Harness target has incomplete coordinates.")
    return HarnessCredentials(
        harness_id=assignment.id,
        catalogue_harness_id=harness.id,
        base_url=base_url,
        model=model,
        token=_decrypt(
            assignment.runtime_token_encrypted or harness.api_token_encrypted
        ),
    )


async def _require_switchable(agent_id: int) -> None:
    if await agent_has_open_tasks(agent_id):
        raise HarnessConflictError(
            "The Harness cannot change while this agent has non-terminal Tasks."
        )


async def _destroy_assignment(
    *,
    agent: Agent,
    assignment: AgentHarness,
    harness: Harness,
) -> None:
    db = get_db()
    provider = get_provider(harness.provider_code)
    assignment.lifecycle_status = "deprovisioning"
    assignment.last_error = None
    await db.commit()
    try:
        await provider.deprovision(agent, _request(assignment, harness, agent))
    except Exception as exc:
        assignment.lifecycle_status = "error"
        assignment.last_error = str(exc)[:10_000]
        await db.commit()
        raise HarnessConflictError(
            "The previous Harness could not be destroyed; no replacement was created."
        ) from exc
    agent.task_harness_id = None
    await db.flush()
    await db.delete(assignment)
    await db.commit()


async def _return_assignments_to_internal(
    harness: Harness,
    assignments: list[AgentHarness],
) -> None:
    """Destroy selected runtimes and make the local Harness effective again."""

    ordered = sorted(assignments, key=lambda item: item.agent_id)
    for assignment in ordered:
        await _require_switchable(assignment.agent_id)
    async with AsyncExitStack() as stack:
        for assignment in ordered:
            await stack.enter_async_context(_agent_lock(assignment.agent_id))
        for assignment in ordered:
            current = await _assignment_for_agent(assignment.agent_id)
            if current is None or not _assignment_matches(current, harness):
                continue
            agent = await get_agent_record(assignment.agent_id)
            if agent is None:
                raise HarnessConflictError(
                    "A Harness assignment references a missing agent."
                )
            await _destroy_assignment(
                agent=agent,
                assignment=current,
                harness=harness,
            )
            agent.agent_driver = "internal"
            await get_db().commit()


async def install(
    agent_id: int,
    data: HarnessSelectionUpdate,
) -> tuple[HarnessRead, HarnessCleanup | None]:
    """Persist a Harness preference without provisioning its runtime.

    If another managed runtime exists, its immutable cleanup request is returned so
    the HTTP layer can destroy it after responding. The newly selected Harness stays
    ``absent`` until an explicit restart or update action provisions it.
    """

    async with _agent_lock(agent_id):
        await _require_switchable(agent_id)
        agent = await get_agent_record(agent_id)
        if agent is None:
            raise LookupError("Agent not found.")
        harness = await _catalogue_choice(data.harness_id)
        if harness is None:
            raise LookupError("Harness not found.")
        if not harness.enabled:
            raise HarnessConflictError("This Harness is disabled.")
        provider = get_provider(harness.provider_code)
        db = get_db()
        old = await _assignment_for_agent(agent_id)
        if (
            old is not None
            and _assignment_matches(old, harness)
            and not bool((old.provider_metadata or {}).get("target_internal"))
        ):
            return _selection_read(old, harness), None

        cleanup: HarnessCleanup | None = None
        operation_id = uuid4()
        if old is not None:
            old_harness = await _harness_for_assignment(old)
            if old_harness is None:
                raise HarnessConflictError("The previous Harness configuration is missing.")
            cleanup = HarnessCleanup(
                assignment_id=old.id,
                agent_id=agent.id,
                operation_id=operation_id,
                provider_code=old_harness.provider_code,
                request=_request(old, old_harness, agent),
            )
            assignment = old
        elif agent.agent_driver != "internal":
            old_provider = get_provider(agent.agent_driver)
            del old_provider
            legacy_harness = Harness(
                id=uuid4(),
                name=agent.agent_driver,
                provider_code=agent.agent_driver,
                driver_code=agent.agent_driver,
            )
            legacy_assignment = AgentHarness(
                id=uuid4(),
                agent_id=agent.id,
                harness_id=None,
                provider_code=agent.agent_driver,
                lifecycle_status="deprovisioning",
            )
            cleanup = HarnessCleanup(
                assignment_id=legacy_assignment.id,
                agent_id=agent.id,
                operation_id=operation_id,
                provider_code=legacy_harness.provider_code,
                request=_request(legacy_assignment, legacy_harness, agent),
            )
            assignment = AgentHarness(agent_id=agent_id)
            db.add(assignment)
        else:
            assignment = AgentHarness(agent_id=agent_id)
            db.add(assignment)

        assignment.harness_id = (
            harness.id if harness.provider_code == "openai_messages" else None
        )
        assignment.provider_code = harness.provider_code
        selected_status: HarnessLifecycleStatus = (
            "absent" if provider.containerized else "ready"
        )
        assignment.lifecycle_status = (
            "deprovisioning" if cleanup is not None else selected_status
        )
        assignment.revision = int(harness.revision or 1)
        assignment.runtime_base_url = None
        assignment.runtime_model = None
        assignment.runtime_token_encrypted = None
        assignment.capabilities = sorted(provider.capabilities())
        assignment.provider_metadata = (
            {
                "selection_operation": str(operation_id),
                "previous_provider_code": cleanup.provider_code,
            }
            if cleanup is not None
            else {}
        )
        assignment.last_error = None
        agent.task_harness_id = (
            harness.id if harness.provider_code == "openai_messages" else None
        )
        agent.agent_driver = provider.driver_code
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HarnessConflictError("This agent already owns a Harness runtime.") from exc
        await db.refresh(assignment)
        if cleanup is not None and cleanup.assignment_id != assignment.id:
            cleanup = HarnessCleanup(
                assignment_id=assignment.id,
                agent_id=cleanup.agent_id,
                operation_id=cleanup.operation_id,
                provider_code=cleanup.provider_code,
                request=cleanup.request,
            )
        return _selection_read(assignment, harness), cleanup


async def select_internal(
    agent_id: int,
) -> tuple[HarnessRead, HarnessCleanup | None]:
    """Persist the local Harness preference and defer external cleanup."""

    async with _agent_lock(agent_id):
        await _require_switchable(agent_id)
        agent = await get_agent_record(agent_id)
        if agent is None:
            raise LookupError("Agent not found.")
        assignment = await _assignment_for_agent(agent_id)
        cleanup: HarnessCleanup | None = None
        if assignment is not None and bool(
            (assignment.provider_metadata or {}).get("target_internal")
        ):
            return internal_read(agent_id), None
        if assignment is not None:
            harness = await _harness_for_assignment(assignment)
            if harness is None:
                raise HarnessConflictError("The selected Harness configuration is missing.")
            operation_id = uuid4()
            cleanup = HarnessCleanup(
                assignment_id=assignment.id,
                agent_id=agent.id,
                operation_id=operation_id,
                provider_code=harness.provider_code,
                request=_request(assignment, harness, agent),
            )
            assignment.lifecycle_status = "deprovisioning"
            assignment.provider_metadata = {
                "selection_operation": str(operation_id),
                "previous_provider_code": harness.provider_code,
                "target_internal": True,
            }
            assignment.last_error = None
        elif agent.agent_driver != "internal":
            provider = get_provider(agent.agent_driver)
            legacy_harness = Harness(
                id=uuid4(),
                name=agent.agent_driver,
                provider_code=agent.agent_driver,
                driver_code=agent.agent_driver,
            )
            legacy_assignment = AgentHarness(
                id=uuid4(),
                agent_id=agent.id,
                harness_id=None,
                provider_code=agent.agent_driver,
                lifecycle_status="deprovisioning",
            )
            del provider
            operation_id = uuid4()
            cleanup = HarnessCleanup(
                assignment_id=legacy_assignment.id,
                agent_id=agent.id,
                operation_id=operation_id,
                provider_code=legacy_harness.provider_code,
                request=_request(legacy_assignment, legacy_harness, agent),
            )
        agent.task_harness_id = None
        agent.agent_driver = "internal"
        await get_db().commit()
        return internal_read(agent_id), cleanup


def _cleanup_matches(assignment: AgentHarness, cleanup: HarnessCleanup) -> bool:
    metadata = cast(Mapping[str, Any], assignment.provider_metadata or {})
    return (
        assignment.id == cleanup.assignment_id
        and str(metadata.get("selection_operation") or "") == str(cleanup.operation_id)
    )


async def cleanup_previous_runtime(cleanup: HarnessCleanup) -> None:
    """Destroy the replaced runtime after the selection response has been sent."""

    async with get_db_session():
        async with _agent_lock(cleanup.agent_id):
            agent = await get_agent_record(cleanup.agent_id)
            if agent is None:
                logger.error(
                    "Harness cleanup skipped because the agent disappeared: agent_id={}",
                    cleanup.agent_id,
                )
                return
            current = await _assignment_for_agent(cleanup.agent_id)
            if current is not None and not _cleanup_matches(current, cleanup):
                # A later selection or explicit recreation already superseded this
                # cleanup. Running the old provider now could delete the new runtime,
                # because every Harness deliberately shares one canonical name.
                return
            try:
                await get_provider(cleanup.provider_code).deprovision(
                    agent,
                    cleanup.request,
                )
            except Exception as exc:
                assignment = await _assignment_for_agent(cleanup.agent_id)
                if assignment is not None and _cleanup_matches(assignment, cleanup):
                    assignment.lifecycle_status = "error"
                    assignment.last_error = str(exc)[:10_000]
                    await get_db().commit()
                logger.exception(
                    "Harness cleanup failed: agent_id={} provider={}",
                    cleanup.agent_id,
                    cleanup.provider_code,
                )
                return

            assignment = await _assignment_for_agent(cleanup.agent_id)
            if assignment is not None and _cleanup_matches(assignment, cleanup):
                if bool((assignment.provider_metadata or {}).get("target_internal")):
                    await get_db().delete(assignment)
                else:
                    selected_harness = await _harness_for_assignment(assignment)
                    assignment.lifecycle_status = (
                        "absent"
                        if selected_harness is not None
                        and get_provider(selected_harness.provider_code).containerized
                        else "ready"
                    )
                    assignment.provider_metadata = {}
                    assignment.last_error = None
                await get_db().commit()


async def _recreate_selected_runtime(agent_id: int) -> None:
    await _require_switchable(agent_id)
    agent = await get_agent_record(agent_id)
    if agent is None:
        raise LookupError("Agent not found.")
    assignment = await _assignment_for_agent(agent_id)
    if assignment is None:
        raise HarnessConflictError("The internal Harness has no runtime to recreate.")
    harness = await _harness_for_assignment(assignment)
    if harness is None:
        raise HarnessConflictError("The selected Harness configuration is missing.")
    provider = get_provider(harness.provider_code)
    db = get_db()
    assignment.lifecycle_status = "provisioning"
    assignment.last_error = None
    await db.commit()
    try:
        # Recreate is intentionally destructive. Every managed provider uses the
        # agent's canonical instance/container name, so no parallel runtime survives.
        request = _request(assignment, harness, agent)
        previous_provider_code = str(
            (assignment.provider_metadata or {}).get("previous_provider_code") or ""
        )
        if previous_provider_code and previous_provider_code != harness.provider_code:
            await get_provider(previous_provider_code).deprovision(agent, request)
        await provider.deprovision(agent, request)
        result = await provider.provision(
            agent,
            request,
            token=_decrypt(harness.api_token_encrypted),
        )
    except Exception as exc:
        assignment.lifecycle_status = "error"
        assignment.last_error = str(exc)[:10_000]
        await db.commit()
        raise
    assignment.runtime_base_url = result.base_url
    assignment.runtime_model = result.model
    assignment.runtime_token_encrypted = _encrypt(result.token)
    assignment.capabilities = sorted(result.capabilities or provider.capabilities())
    assignment.provider_metadata = dict(result.metadata)
    assignment.lifecycle_status = "ready"
    assignment.last_error = None
    await db.commit()


async def run_action_in_background(agent_id: int, action: HarnessAction) -> None:
    """Run long lifecycle work in an isolated database context."""

    async with get_db_session():
        async with _agent_lock(agent_id):
            try:
                assignment = await _assignment_for_agent(agent_id)
                if assignment is None:
                    raise HarnessConflictError(
                        "The internal Harness has no external runtime to supervise."
                    )
                if action not in {"restart", "update"} and assignment.lifecycle_status != "ready":
                    raise HarnessConflictError(
                        "Use restart or update to create the selected Harness runtime."
                    )
                from .configuration import configured_provider_capabilities

                harness = await _harness_for_assignment(assignment)
                if harness is None or action not in await configured_provider_capabilities(harness.provider_code):
                    raise HarnessConflictError("The Harness policy no longer permits this action.")
                if action in {"restart", "update"}:
                    await _recreate_selected_runtime(agent_id)
                    return
                if assignment.lifecycle_status != "ready":
                    raise HarnessConflictError(
                        "Use restart or update to create the selected Harness runtime."
                    )
                agent = await get_agent_record(agent_id)
                if agent is None:
                    raise LookupError("Agent not found.")
                harness = await _harness_for_assignment(assignment)
                if harness is None:
                    raise HarnessConflictError(
                        "The selected Harness configuration is missing."
                    )
                await get_provider(harness.provider_code).run_action(
                    agent,
                    action,
                )
            except Exception as exc:
                assignment = await _assignment_for_agent(agent_id)
                if assignment is not None:
                    assignment.lifecycle_status = "error"
                    assignment.last_error = str(exc)[:10_000]
                    await get_db().commit()
                logger.exception(
                    "Harness background action failed: agent_id={} action={}",
                    agent_id,
                    action,
                )


__all__ = [
    "HarnessConflictError",
    "HarnessCleanup",
    "cleanup_previous_runtime",
    "create_catalogue_harness",
    "delete_catalogue_harness",
    "execution_credentials",
    "get_catalogue_harness",
    "get_for_agent",
    "install",
    "list_catalogue",
    "probe_openai_harness",
    "resolve_target",
    "run_action_in_background",
    "select_internal",
    "update_catalogue_harness",
]
