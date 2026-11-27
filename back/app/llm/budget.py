"""USD envelopes checked at physical call admission under a per-account lock."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Numeric, cast, func, or_, select

from core.database import get_db

from .budget_models import InferenceBudget, InferenceCreditGrant
from .models import LLMCall
from .subscription_policy import LLMExecutionAuthority, current_execution_authority
from .user_attribution import resolve_call_user

Period = Literal["session", "weekly", "monthly"]
PERIODS: tuple[Period, ...] = ("session", "weekly", "monthly")
SESSION = timedelta(hours=5)
WEEK = timedelta(days=7)
MONDAY = datetime(1970, 1, 5, tzinfo=timezone.utc)
ZERO = Decimal(0)
_calls = LLMCall.__table__.c


class Envelope(BaseModel):
    period: Period
    starts_at: datetime | None
    resets_at: datetime | None
    limit: Decimal | None
    granted: Decimal
    spent: Decimal
    exhausted: bool


class BudgetUnavailable(RuntimeError):
    status_code = 429

    def __init__(self, envelopes: list[Envelope], *, busy: bool = False, detail: dict[str, object] | None = None) -> None:
        self.busy = busy
        self.resets_at = max((row.resets_at for row in envelopes if row.resets_at is not None), default=None)
        self.periods = [row.period for row in envelopes]
        windows = ", ".join(self.periods)
        message = ("Another inference is finishing on this budget. Retry shortly." if busy
                   else f"Inference budget exhausted ({windows}).")
        if self.resets_at is not None:
            message += f" Resets at {self.resets_at.isoformat()}."
        self._detail = detail or {
            "code": "inference_budget_busy" if self.busy else "inference_budget_exhausted",
            "message": message, "periods": self.periods,
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
        }
        super().__init__(str(self._detail["message"]))

    def detail(self) -> dict[str, object]:
        return self._detail


async def lock_budget(user_id: int) -> None:
    await get_db().execute(select(func.pg_advisory_xact_lock(119618005, user_id)))


async def policy_for_write(user_id: int) -> InferenceBudget:
    db = get_db()
    policy = await db.get(InferenceBudget, user_id, populate_existing=True)
    if policy is None:
        policy = InferenceBudget(user_id=user_id, weekly_reset_hour=0)
        db.add(policy)
        await db.flush()
    return policy


def bounds(period: Period, now: datetime, policy: InferenceBudget | None) -> tuple[datetime | None, datetime | None]:
    now = now.astimezone(timezone.utc)
    if period == "session":
        start = policy.session_started_at if policy else None
        return (start, start + SESSION) if start is not None and start <= now < start + SESSION else (None, None)
    if period == "weekly":
        anchor = MONDAY + timedelta(hours=policy.weekly_reset_hour if policy else 0)
        start = anchor + (now - anchor) // WEEK * WEEK
        return start, start + WEEK
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, (start + timedelta(days=32)).replace(day=1)


def period_limit(policy: InferenceBudget | None, period: Period) -> Decimal | None:
    if policy is None:
        return None
    return {"session": policy.session_limit, "weekly": policy.weekly_limit, "monthly": policy.monthly_limit}[period]


async def envelopes(user_id: int, policy: InferenceBudget | None, now: datetime) -> list[Envelope]:
    db = get_db()
    ranges: dict[Period, tuple[datetime | None, datetime | None]] = {
        period: bounds(period, now, policy) for period in PERIODS
    }
    # Historical billed amounts predate the separate inference valuation.
    cost = func.greatest(_calls.cost, _calls.inference_cost)
    money = Numeric(24, 6)
    spending = (await db.execute(select(*(
        cast(func.coalesce(func.sum(cost).filter(_calls.started_at >= start, _calls.started_at < end), 0), money)
        if start is not None and end is not None else cast(0, money)
        for start, end in ranges.values()
    )).where(_calls.user_id == user_id, _calls.started_at >= min(
        start for start, _ in ranges.values() if start is not None
    )))).one()
    grant = InferenceCreditGrant
    additions = (await db.execute(select(*(
        func.coalesce(func.sum(grant.amount).filter(
            grant.period == period, grant.window_start == start), ZERO)
        if start is not None else cast(ZERO, money)
        for period, (start, _) in ranges.items()
    )).where(grant.user_id == user_id))).one()
    result: list[Envelope] = []
    for index, (period, (start, end)) in enumerate(ranges.items()):
        limit, spent, granted = period_limit(policy, period), spending[index], additions[index]
        result.append(Envelope(period=period, starts_at=start, resets_at=end, limit=limit,
                               spent=spent, granted=granted, exhausted=limit is not None and spent >= limit + granted))
    return result


def capped(policy: InferenceBudget | None) -> bool:
    return any(period_limit(policy, period) is not None for period in PERIODS)


async def budget_limited(user_id: int | None) -> bool:
    return user_id is not None and capped(await get_db().get(InferenceBudget, user_id, populate_existing=True))


async def budget_blocked(user_id: int | None) -> bool:
    if user_id is None:
        return False
    policy = await get_db().get(InferenceBudget, user_id, populate_existing=True)
    return capped(policy) and any(window.exhausted for window in
                                  await envelopes(user_id, policy, datetime.now(timezone.utc)))


async def automatic_budget_blocked(*, task_id: UUID | None = None, process_run_id: UUID | None = None,
                                   source_kind: str | None = None, source_id: str | None = None,
                                   requester_user_id: int | None = None) -> bool:
    db = get_db()
    authority = LLMExecutionAuthority(source_kind=source_kind, source_id=source_id)
    user_id = await resolve_call_user(db, LLMCall(task_id=task_id, process_run_id=process_run_id,
                                      requester_user_id=requester_user_id), None, authority)
    if user_id is not None:
        return await budget_blocked(user_id)
    if source_kind == "conversation_round" and source_id is not None:
        try:
            round_id = UUID(source_id.split(":", 1)[0])
        except ValueError:
            return False
        return await _capped_shared_round(round_id)
    return False


async def _capped_shared_round(round_id: UUID | None) -> bool:
    if round_id is None:
        return False
    from app.conversation import ConversationRoundMessage
    from app.messenger import Message

    related = (select(ConversationRoundMessage.message_id)
        .join(Message, Message.id == ConversationRoundMessage.message_id)
        .join(InferenceBudget, InferenceBudget.user_id == Message.requester_user_id)
        .where(ConversationRoundMessage.round_id == round_id, ConversationRoundMessage.role == "input",
               or_(InferenceBudget.session_limit.is_not(None), InferenceBudget.weekly_limit.is_not(None),
                   InferenceBudget.monthly_limit.is_not(None))))
    return bool(await get_db().scalar(select(related.exists())))


async def _assert_chargeable_round(round_id: UUID | None) -> None:
    if await _capped_shared_round(round_id):
        raise BudgetUnavailable([], detail={
            "code": "inference_budget_shared_round", "message": "This shared response has no single budget owner.",
        })


async def check_inference_budget(user_id: int | None) -> None:
    if user_id is None:
        return
    policy = await get_db().get(InferenceBudget, user_id, populate_existing=True)
    if capped(policy):
        blocked = [row for row in await envelopes(user_id, policy, datetime.now(timezone.utc)) if row.exhausted]
        if blocked:
            raise BudgetUnavailable(blocked)


async def admit_budgeted_call(call: LLMCall) -> None:
    user_id = call.user_id
    if user_id is None:
        await _assert_chargeable_round(call.conversation_round_id)
        return
    db = get_db()
    await lock_budget(user_id)
    policy = await policy_for_write(user_id)
    now = datetime.now(timezone.utc)
    if capped(policy):
        if await db.scalar(select(select(_calls.id).where(_calls.user_id == user_id, _calls.status == "running").exists())):
            raise BudgetUnavailable([], busy=True)
        blocked = [row for row in await envelopes(user_id, policy, now) if row.exhausted]
        if blocked:
            raise BudgetUnavailable(blocked)
    if bounds("session", now, policy)[0] is None:
        policy.session_started_at = now
    call.started_at = now


async def check_context_budget(call: LLMCall, authenticated_user: int | None) -> None:
    authority = current_execution_authority()
    if call.requester_user_id is None and authority is not None:
        call.requester_user_id = authority.requester_user_id
    user_id = await resolve_call_user(get_db(), call, authenticated_user, authority)
    if user_id is None:
        await _assert_chargeable_round(call.conversation_round_id)
    await check_inference_budget(user_id)
