"""Human account supervision and audited budget administration."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from core.authorize import Privileges, authorize, check_privilege
from core.database import get_db
from core.i18n import tr
from core.team import has_team_manager, lock_team_sharing, managed_team_users
from core.user import UserModel, get_current_user, require_active_web_session

from .budget import Envelope, Period, bounds, envelopes, lock_budget, period_limit, policy_for_write
from .budget_models import InferenceBudget, InferenceCreditGrant, InferenceCreditRequest

router = APIRouter(prefix="/llm-budget", tags=["Inference budget"], dependencies=[Depends(require_active_web_session)])
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=6, allow_inf_nan=False)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=6, allow_inf_nan=False)]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyInput(StrictInput):
    session_limit: Money | None
    weekly_limit: Money | None
    monthly_limit: Money | None


class RequestInput(StrictInput):
    period: Period
    amount: PositiveMoney


class GrantInput(StrictInput):
    operation_id: UUID
    period: Period
    amount: PositiveMoney


class ReviewInput(StrictInput):
    decision: Literal["approved", "rejected"]


class CreditRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    period: Period
    amount: Decimal
    status: Literal["pending", "approved", "rejected"]


class AccountBudget(BaseModel):
    user_id: int
    label: str
    envelopes: list[Envelope]
    requests: list[CreditRequestRead]


class ManagedAccountBudget(AccountBudget):
    can_configure: bool
    can_manage_credits: bool


class BudgetOverview(BaseModel):
    account: AccountBudget
    can_configure_own: bool
    can_request_credit: bool


class AccountsPage(BaseModel):
    items: list[ManagedAccountBudget]
    total: int


async def _current_user() -> UserModel:
    user = await get_current_user()
    if user is None:
        raise HTTPException(401)
    return user


async def _account(user: UserModel, policy: InferenceBudget | None, *, include_requests: bool) -> AccountBudget:
    requests = []
    if include_requests:
        rows = await get_db().scalars(select(InferenceCreditRequest).where(
            InferenceCreditRequest.user_id == user.id,
        ).order_by(InferenceCreditRequest.created_at.desc()).limit(25))
        requests = [CreditRequestRead.model_validate(row) for row in rows]
    return AccountBudget(user_id=user.id, label=user.display_name or user.email,
                         envelopes=await envelopes(user.id, policy, datetime.now(timezone.utc)),
                         requests=requests)


async def _manages_user(manager_user_id: int, user_id: int) -> bool:
    statement = managed_team_users(manager_user_id, member_user_id=user_id)
    return bool(await get_db().scalar(select(statement.exists())))


@router.get("/me", response_model=BudgetOverview)
@authorize(privileges=[])
async def my_budget() -> BudgetOverview:
    user = await _current_user()
    db = get_db()
    can_configure = await check_privilege(user, Privileges.LLM_BUDGET_ADMIN, db)
    return BudgetOverview(account=await _account(user, await db.get(InferenceBudget, user.id), include_requests=True),
                          can_configure_own=can_configure or await check_privilege(user, Privileges.LLM_BUDGET_EDIT_OWN, db),
                          can_request_credit=await has_team_manager(user.id))


@router.get("/managed", response_model=AccountsPage)
@authorize(privileges=[])
async def managed_budgets(page: Annotated[int, Query(ge=1)] = 1,
                          page_size: Annotated[int, Query(ge=10, le=500)] = 50,
                          configure: bool | None = None) -> AccountsPage:
    if page_size not in (10, 20, 50, 100, 500):
        raise HTTPException(422)
    user = await _current_user()
    db = get_db()
    all_accounts = await check_privilege(user, Privileges.LLM_BUDGET_ADMIN, db)
    if configure and not all_accounts:
        raise HTTPException(403)
    is_managed = UserModel.id.in_(managed_team_users(user.id))
    query = (select(UserModel, InferenceBudget, is_managed.label("is_managed"))
             .outerjoin(InferenceBudget, InferenceBudget.user_id == UserModel.id)
             .where(UserModel.is_active.is_(True), UserModel.id != user.id))
    if configure is False or not all_accounts:
        query = query.where(is_managed)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.order_by(UserModel.id).offset((page - 1) * page_size).limit(page_size))
    items: list[ManagedAccountBudget] = []
    for user_row, policy, can_manage in result.tuples():
        account = await _account(user_row, policy, include_requests=can_manage)
        items.append(ManagedAccountBudget(user_id=account.user_id, label=account.label,
                                          envelopes=account.envelopes, requests=account.requests,
                                          can_configure=all_accounts or can_manage, can_manage_credits=can_manage))
    return AccountsPage(items=items, total=total or 0)


@router.put("/policies/{user_id}", status_code=204)
@authorize(privileges=[])
async def set_policy(user_id: int, body: PolicyInput) -> None:
    actor = await _current_user()
    db = get_db()
    await lock_team_sharing(shared=True)
    if not await check_privilege(actor, Privileges.LLM_BUDGET_ADMIN, db):
        allowed = (await check_privilege(actor, Privileges.LLM_BUDGET_EDIT_OWN, db) if user_id == actor.id
                   else await _manages_user(actor.id, user_id))
        if not allowed:
            raise HTTPException(403)
    await lock_budget(user_id)
    target = await db.get(UserModel, user_id, populate_existing=True)
    if target is None or not target.is_active:
        raise HTTPException(404)
    policy = await policy_for_write(user_id)
    policy.session_limit = body.session_limit
    policy.weekly_limit = body.weekly_limit
    policy.monthly_limit = body.monthly_limit
    await db.commit()


@router.post("/requests", response_model=CreditRequestRead, status_code=201)
@authorize(privileges=[])
async def request_credit(body: RequestInput) -> CreditRequestRead:
    actor = await _current_user()
    db = get_db()
    await lock_team_sharing(shared=True)
    if not await has_team_manager(actor.id):
        raise HTTPException(409)
    await lock_budget(actor.id)
    policy = await policy_for_write(actor.id)
    if period_limit(policy, body.period) is None:
        raise HTTPException(409)
    pending = await db.scalar(select(InferenceCreditRequest).where(
        InferenceCreditRequest.user_id == actor.id, InferenceCreditRequest.period == body.period,
        InferenceCreditRequest.status == "pending",
    ))
    if pending is None:
        pending = InferenceCreditRequest(user_id=actor.id, period=body.period, amount=body.amount)
        db.add(pending)
        await db.flush()
    result = CreditRequestRead.model_validate(pending)
    await db.commit()
    return result


async def _managed_policy(actor: UserModel, user_id: int) -> InferenceBudget:
    await lock_team_sharing(shared=True)
    target = await get_db().get(UserModel, user_id, populate_existing=True)
    if target is None or not target.is_active or not await _manages_user(actor.id, user_id):
        raise HTTPException(404)
    await lock_budget(user_id)
    return await policy_for_write(user_id)


async def _grant(policy: InferenceBudget, actor: UserModel, period: Period, value: Decimal,
                 operation_id: UUID, request_id: UUID | None = None) -> None:
    db = get_db()
    existing = await db.get(InferenceCreditGrant, operation_id)
    if existing is None:
        if period_limit(policy, period) is None:
            raise HTTPException(409)
        start, _ = bounds(period, datetime.now(timezone.utc), policy)
        if start is None:
            raise HTTPException(409, detail=await tr("inference_budget.grant_requires_active_window"))
        inserted = await db.scalar(insert(InferenceCreditGrant).values(
            id=operation_id, request_id=request_id, user_id=policy.user_id, granted_by_user_id=actor.id,
            period=period, amount=value, window_start=start,
        ).on_conflict_do_nothing(index_elements=[InferenceCreditGrant.id]).returning(InferenceCreditGrant.id))
        if inserted is not None:
            return
        existing = await db.get(InferenceCreditGrant, operation_id)
    if existing is None or (existing.user_id, existing.granted_by_user_id, existing.period, existing.amount,
                            existing.request_id) != (policy.user_id, actor.id, period, value, request_id):
        raise HTTPException(409)


@router.post("/grants/{user_id}", status_code=204)
@authorize(privileges=[])
async def grant_credit(user_id: int, body: GrantInput) -> None:
    actor = await _current_user()
    policy = await _managed_policy(actor, user_id)
    await _grant(policy, actor, body.period, body.amount, body.operation_id)
    await get_db().commit()


@router.post("/requests/{request_id}/review", status_code=204)
@authorize(privileges=[])
async def review_request(request_id: UUID, body: ReviewInput) -> None:
    actor = await _current_user()
    db = get_db()
    request = await db.get(InferenceCreditRequest, request_id)
    if request is None:
        raise HTTPException(404)
    policy = await _managed_policy(actor, request.user_id)
    await db.refresh(request)
    if request.status == body.decision:
        return
    if request.status != "pending":
        raise HTTPException(409)
    if body.decision == "approved":
        period = RequestInput.model_validate({"period": request.period, "amount": request.amount}).period
        await _grant(policy, actor, period, request.amount, uuid4(), request.id)
    request.status = body.decision
    request.reviewer_user_id = actor.id
    request.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
