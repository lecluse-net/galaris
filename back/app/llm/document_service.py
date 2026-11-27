"""Admission, ownership, cancellation and scheduler roots for document analysis."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.file_share import ResourceContext, prepared_resource, require_document_source_scope, resource_info
from app.services.facade import AuthorizationClosed, administration_scope, authorized_request, claim_deferred_dispatch, finish_action, register_deferred_dispatch
from core.database import get_db
from core.user import get_current_user_id
from .document_analysis import advance_step, cancel_step, prepare_input
from .document_contracts import DocumentAnalysisError, DocumentAnalysisSnapshot
from .document_store import TERMINAL_STATUSES, publish, snapshot
from .models import LLMDocumentAnalysis
from .subscription_policy import LLMExecutionAuthority, current_execution_authority, llm_execution_scope
from .budget import BudgetUnavailable, automatic_budget_blocked


async def start_analysis(agent_id: int, input_data: dict[str, Any], *,
                         task_id: UUID | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
    from .document_analysis import DocumentAdmission

    admission = DocumentAdmission.model_validate(input_data)
    await require_document_source_scope(ResourceContext(agent_id=agent_id, runtime=admission.runtime, task_id=task_id),
        admission.uri)
    if idempotency_key is not None and len(idempotency_key) > 255:
        raise ValueError("Document analysis idempotency key exceeds 255 characters")
    db = get_db()
    if idempotency_key:
        existing = await db.scalar(select(LLMDocumentAnalysis).where(
            LLMDocumentAnalysis.agent_id == agent_id,
            LLMDocumentAnalysis.idempotency_key == idempotency_key,
        ))
        if existing:
            for key in ("uri", "revision", "question", "runtime", "max_calls", "model_slot"):
                if existing.input.get(key) != admission.model_dump()[key]:
                    raise ValueError("An analysis identity cannot be reused for another request")
            return await read_analysis(agent_id, existing.id, runtime=admission.runtime)
    payload = await prepare_input(agent_id, admission.model_dump())
    authority = current_execution_authority() or LLMExecutionAuthority(requester_user_id=get_current_user_id())
    dispatch: dict[str, Any] = {"input": payload}
    await db.commit()
    permit = await register_deferred_dispatch(dispatch)
    if permit:
        dispatch["authorization_permit"] = str(permit)
    key = uuid4()
    added = await db.scalar(insert(LLMDocumentAnalysis).values(
        id=key, agent_id=agent_id, task_id=task_id, input=payload,
        idempotency_key=idempotency_key or None, authority=asdict(authority), dispatch=dispatch,
    ).on_conflict_do_nothing().returning(LLMDocumentAnalysis.id))
    await db.commit()
    if added is None:
        existing = await db.scalar(select(LLMDocumentAnalysis).where(
            LLMDocumentAnalysis.agent_id == agent_id,
            LLMDocumentAnalysis.idempotency_key == idempotency_key,
        ))
        if existing is None:
            raise RuntimeError("Analysis admission did not persist")
        for field in ("uri", "revision", "question", "runtime", "max_calls", "model_slot"):
            if existing.input.get(field) != payload[field]:
                await finish_action(permit, outcome="failed", deferred=True)
                raise ValueError("An analysis identity cannot be reused for another request")
        await finish_action(permit, receipt={"analysis_id": str(existing.id)}, deferred=True)
        key = existing.id
    return await read_analysis(agent_id, key, runtime=admission.runtime)


async def _scoped_analysis(agent_id: int, analysis_id: UUID) -> LLMDocumentAnalysis:
    scope = await administration_scope(agent_id, "document")
    scope.require_administration()
    row = await get_db().get(LLMDocumentAnalysis, analysis_id, populate_existing=True)
    if row is None or not scope.allows(row.agent_id):
        raise PermissionError("Document analysis not accessible")
    return row


async def _analysis_source_context(row: LLMDocumentAnalysis, agent_id: int, runtime: str) -> ResourceContext:
    owns_run = row.agent_id == agent_id
    ctx = ResourceContext(agent_id=agent_id, runtime=runtime, task_id=row.task_id if owns_run else None)
    reference = await require_document_source_scope(ctx, str(row.input["uri"]))
    if not owns_run and reference.scheme not in {"document", "data"}:
        raise PermissionError("Only analyses of native documents can be accessed through delegation")
    return ctx


async def _readable_analysis(agent_id: int, analysis_id: UUID, *, runtime: str) -> LLMDocumentAnalysis:
    row = await _scoped_analysis(agent_id, analysis_id)
    ctx = await _analysis_source_context(row, agent_id, runtime)
    uri, revision = str(row.input["uri"]), row.input.get("revision")
    await resource_info(ctx, uri, revision=revision)
    if row.checkpoint.get("source_sha256"):
        async with prepared_resource(ctx, uri, revision=revision) as (document, _):
            if document.sha256 != row.checkpoint["source_sha256"]:
                raise ValueError("Document analysis belongs to an obsolete source version")
    return row


async def read_analysis(agent_id: int, analysis_id: UUID, *, runtime: str) -> dict[str, Any]:
    row = await _readable_analysis(agent_id, analysis_id, runtime=runtime)
    # run_id is retained solely for compatibility with existing tool arguments.
    return {"analysis_id": str(row.id), "run_id": str(row.id),
            **snapshot(row).model_dump(mode="json"), "source_uri": row.input["uri"],
            "source_revision": row.input.get("revision")}


async def advance_analysis(analysis_id: UUID) -> DocumentAnalysisSnapshot:
    result = await advance_step(analysis_id)
    return await publish(analysis_id, result)


async def cancel_analysis(agent_id: int, analysis_id: UUID, *, runtime: str) -> dict[str, Any]:
    row = await _scoped_analysis(agent_id, analysis_id)
    if row.agent_id != agent_id:
        ctx = await _analysis_source_context(row, agent_id, runtime)
        await resource_info(ctx, str(row.input["uri"]), revision=row.input.get("revision"))
    result = await cancel_step(analysis_id)
    result = await publish(analysis_id, result)
    if result.status in TERMINAL_STATUSES:
        await settle_authorization(analysis_id, result)
    return {"analysis_id": str(analysis_id), "run_id": str(analysis_id), "status": result.status}


async def settle_authorization(analysis_id: UUID, result: DocumentAnalysisSnapshot) -> None:
    """Idempotently settle a receipt; a crash before the marker is retried by the scheduler."""
    db = get_db()
    row = await db.get(LLMDocumentAnalysis, analysis_id, populate_existing=True)
    assert row is not None
    value = row.dispatch.get("authorization_permit")
    await db.commit()
    if value:
        await finish_action(UUID(str(value)), receipt=result.model_dump(mode="json"), deferred=True,
            outcome="completed" if result.status == "success" else
                    "outcome_unknown" if result.status == "unknown" else "failed")
    await db.execute(update(LLMDocumentAnalysis).where(LLMDocumentAnalysis.id == analysis_id)
        .values(authorization_settled=True))
    await db.commit()


async def analysis_tick() -> None:
    """Advance one fairly selected analysis under an expiring, cross-worker lease."""
    db = get_db()
    now = datetime.now(timezone.utc)
    row = await db.scalar(select(LLMDocumentAnalysis).where(
        or_(LLMDocumentAnalysis.status.not_in(TERMINAL_STATUSES), and_(
            LLMDocumentAnalysis.authorization_settled.is_(False),
            LLMDocumentAnalysis.dispatch["authorization_permit"].astext.is_not(None),
        )),
        or_(LLMDocumentAnalysis.lease_expires_at.is_(None), LLMDocumentAnalysis.lease_expires_at < now),
    ).order_by(LLMDocumentAnalysis.updated_at, LLMDocumentAnalysis.id)
        .limit(1).with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if row is None:
        await db.commit()
        return
    key, lease = row.id, uuid4()
    row.lease_token, row.lease_expires_at = lease, now + timedelta(seconds=1500)
    authority = LLMExecutionAuthority(**row.authority)
    dispatch, agent_id = dict(row.dispatch), row.agent_id
    deferred_until = None
    if row.status not in TERMINAL_STATUSES and not row.checkpoint.get("pending_inference") and not row.checkpoint.get("cancelled"):
        if await automatic_budget_blocked(task_id=row.task_id, requester_user_id=authority.requester_user_id,
                                          source_kind=authority.source_kind, source_id=authority.source_id):
            row.lease_token, row.lease_expires_at = None, now + timedelta(seconds=60)
            await db.commit()
            return
    await db.commit()
    permit = UUID(str(dispatch["authorization_permit"])) if dispatch.get("authorization_permit") else None
    try:
        if permit and row.status not in TERMINAL_STATUSES and not row.checkpoint.get("cancelled"):
            await claim_deferred_dispatch(permit, agent_id=agent_id,
                payload={k: v for k, v in dispatch.items() if k not in {"authorization_permit", "claimed"}},
                continuation=bool(dispatch.get("claimed")))
            # Keep the signed payload unchanged; persist continuation separately.
            row = await db.get(LLMDocumentAnalysis, key, populate_existing=True)
            assert row is not None
            row.dispatch = {**row.dispatch, "claimed": True}
            await db.commit()
        with llm_execution_scope(**asdict(authority)), authorized_request(permit):
            result = await advance_analysis(key)
        if result.status in TERMINAL_STATUSES:
            await settle_authorization(key, result)
    except BudgetUnavailable:
        await db.rollback()
        deferred_until = datetime.now(timezone.utc) + timedelta(seconds=60)
    except (PermissionError, AuthorizationClosed):
        result = await publish(key, DocumentAnalysisSnapshot(status="error", error=DocumentAnalysisError(
            code="document_authorization_unavailable", message="The analysis authorization is no longer available")))
        await settle_authorization(key, result)
    finally:
        await db.execute(update(LLMDocumentAnalysis).where(
            LLMDocumentAnalysis.id == key, LLMDocumentAnalysis.lease_token == lease,
        ).values(lease_token=None, lease_expires_at=deferred_until, updated_at=datetime.now(timezone.utc)))
        await db.commit()
