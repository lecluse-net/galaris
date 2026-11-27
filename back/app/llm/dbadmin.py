"""Programmatic DbAdmin data source for the permanent LLM profile baseline."""

from __future__ import annotations

from typing import cast

from sqlalchemy import Table, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import (
    DbAdminDataSource,
    DbAdminDataset,
    DbAdminDatasetResult,
    DbAdminRegistry,
    DbAdminAction,
    DbAdminPhase,
    SchemaTransitionSet,
)
from core.params import Param, Params, params_service

from .profile_models import LlmProfile
from .profile_service import DEFAULT_PROFILE_LABEL
from .profile_codes import profile_code
from .user_attribution import backfill_call_users, call_users_backfilled
from .initial_configuration import (
    initial_configuration_complete,
    initialize_configuration,
    needs_initial_configuration,
)


async def _default_profile_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    labels = tuple((await session.scalars(select(LlmProfile.label))).all())
    if DEFAULT_PROFILE_LABEL in labels or not labels:
        occupied = set((await session.scalars(select(LlmProfile.code))).all())
        return ({"label": DEFAULT_PROFILE_LABEL, "code": profile_code(DEFAULT_PROFILE_LABEL, occupied)},)
    # An installation already containing profiles uses its first profile as
    # baseline; do not inject an additional administrator-visible row.
    return ()


async def _current_profile_rows(
    session: AsyncSession,
) -> tuple[dict[str, object], ...]:
    profile_ids = tuple(
        int(value)
        for value in (await session.scalars(select(LlmProfile.id).order_by(LlmProfile.id))).all()
    )
    if not profile_ids:
        raise RuntimeError("DbAdmin could not establish an LLM profile baseline")
    current = await session.scalar(
        select(Param.value).where(Param.name == Params.LLM_PROFILE_ID)
    )
    try:
        current_id = int(current) if current is not None else None
    except ValueError:
        current_id = None
    selected = current_id if current_id in profile_ids else profile_ids[0]
    return ({"name": Params.LLM_PROFILE_ID, "value": str(selected)},)


async def _reload_runtime_params(
    _session: AsyncSession,
    _result: DbAdminDatasetResult,
) -> None:
    await params_service.refresh()


def _datasets() -> tuple[DbAdminDataset, ...]:
    return (
        DbAdminDataset(
            key="app.llm.default_profile",
            table=cast(Table, LlmProfile.__table__),
            natural_key=("label",),
            rows=_default_profile_rows,
            update_columns=(),
            depends_on=("core.params.declarations",),
        ),
        DbAdminDataset(
            key="app.llm.current_profile",
            table=cast(Table, Param.__table__),
            natural_key=("name",),
            rows=_current_profile_rows,
            update_columns=("value",),
            after_merge=_reload_runtime_params,
            depends_on=("app.llm.default_profile",),
        ),
    )


DATA_SOURCE = DbAdminDataSource(key="app.llm", factory=_datasets)


def _needs_profile_codes(transitions: SchemaTransitionSet) -> bool:
    return any(item.key == "llm_profiles.code" for item in transitions.required_columns)


async def _backfill_profile_codes(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    table = cast(Table, LlmProfile.__table__)
    occupied = set((await session.scalars(select(LlmProfile.code).where(LlmProfile.code.is_not(None)))).all())
    rows = (await session.execute(
        select(LlmProfile.id, LlmProfile.label).where(LlmProfile.code.is_(None)).order_by(LlmProfile.id)
    )).all()
    for row in rows:
        code = profile_code(row.label, occupied)
        await session.execute(update(table).where(table.c.id == row.id).values(code=code))
        occupied.add(code)


async def _profile_codes_complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    return not await session.scalar(
        select(func.count()).select_from(LlmProfile).where(LlmProfile.code.is_(None))
    )


def _retires_call_costs(transitions: SchemaTransitionSet) -> bool:
    return "llm_call_costs" in transitions.removed_tables


async def _call_costs_transferred(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    if await session.scalar(text("SELECT to_regclass('public.llm_call_costs')")) is None:
        return True
    return not await session.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM public.llm_call_costs k
            LEFT JOIN public.llm_calls c ON c.id = k.id
            WHERE c.id IS NULL OR (k.call_id IS NOT NULL AND k.call_id <> k.id)
               OR ROW(c.cost, c.inference_cost, c.cost_estimated, c.is_subscription, c.usage->'_galaris_cost')
                  IS DISTINCT FROM
                  ROW(k.cost, k.inference_cost, k.cost_estimated, k.is_subscription, k.evidence->'_galaris_cost')
        )
    """))


async def _transfer_call_costs(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    await session.execute(text("""
        INSERT INTO public.llm_calls (
            id, task_id, agent_id, conversation_round_id, correlation_ref, purpose, status,
            started_at, completed_at, created_at, updated_at, deleted_at, duration,
            cost, inference_cost, cost_estimated, is_subscription, usage,
            provider_name, requested_model, effective_model, stream, request_messages,
            prompt, system_prompt, response_text, reasoning, tool_calls,
            input_tokens, output_tokens, total_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens
        )
        SELECT k.id, k.task_id, k.agent_id, k.conversation_round_id, k.correlation_ref, k.purpose,
            CASE WHEN k.status = 'running' THEN 'cancelled' ELSE k.status END,
            k.started_at, coalesce(k.completed_at, k.started_at), k.started_at,
            coalesce(k.completed_at, k.started_at), now(),
            greatest(0, extract(epoch FROM k.completed_at - k.started_at)),
            k.cost, k.inference_cost, k.cost_estimated, k.is_subscription,
            k.evidence || '{"trace_retention": "expired"}'::jsonb,
            '', '', '', false, '[]', '', '', '', '', '[]', 0, 0, 0, 0, 0, 0
        FROM public.llm_call_costs k
        WHERE NOT EXISTS (SELECT 1 FROM public.llm_calls c WHERE c.id = k.id)
        ON CONFLICT (id) DO NOTHING
    """))
    # The old register was authoritative for the Task and Lab reports.
    await session.execute(text("""
        UPDATE public.llm_calls c
        SET cost = k.cost, inference_cost = k.inference_cost, cost_estimated = k.cost_estimated,
            is_subscription = k.is_subscription, usage = (c.usage - '_galaris_cost') || k.evidence
        FROM public.llm_call_costs k
        WHERE c.id = k.id AND (k.call_id IS NULL OR k.call_id = k.id)
          AND ROW(c.cost, c.inference_cost, c.cost_estimated, c.is_subscription, c.usage->'_galaris_cost')
              IS DISTINCT FROM
              ROW(k.cost, k.inference_cost, k.cost_estimated, k.is_subscription, k.evidence->'_galaris_cost')
    """))


async def _backfill_call_users(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    await backfill_call_users(session)


async def _call_users_complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    return await call_users_backfilled(session)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_data_source(DATA_SOURCE)
    registry.register_action(DbAdminAction(
        key="app.llm.initial_configuration", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="openrouter-reference-v1", predicate=needs_initial_configuration,
        handler=initialize_configuration, postcondition=initial_configuration_complete,
    ))
    registry.register_action(DbAdminAction(
        key="app.llm.profile_codes", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="ascii-stable-codes-v1", predicate=_needs_profile_codes,
        handler=_backfill_profile_codes, postcondition=_profile_codes_complete,
    ))
    registry.register_action(DbAdminAction(
        key="app.llm.consolidate_call_costs", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="historized-physical-call-costs-v1", predicate=_retires_call_costs,
        handler=_transfer_call_costs, postcondition=_call_costs_transferred,
        requires_schema=frozenset({"llm_calls.deleted_at"}),
    ))
    registry.register_action(DbAdminAction(
        key="app.llm.attribute_call_users", phase=DbAdminPhase.AFTER_DATASET,
        checksum="call-user-provenance-v1",
        predicate=lambda delta: delta.column_added("llm_calls", "user_id"),
        handler=_backfill_call_users, postcondition=_call_users_complete,
        requires_schema=frozenset({"llm_calls.user_id", "lab_evaluation_runs", "multimedia_generations",
                                   "conversation_task_links", "deep_sessions", "voice_sessions", "dream_receipts",
                                   "contact_discovery_jobs"}),
    ))
