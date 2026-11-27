import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.llm.budget import PERIODS, BudgetUnavailable, admit_budgeted_call, bounds, envelopes
from app.llm.budget_models import InferenceBudget, InferenceCreditGrant
from app.llm.models import LLMCall
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel, create_access_token


def test_windows_use_first_call_fixed_weekly_reset_and_calendar_month():
    now = datetime(2026, 12, 31, 23, tzinfo=timezone.utc)
    policy = InferenceBudget(weekly_reset_hour=25, session_started_at=now - timedelta(hours=4))
    assert bounds("session", now, policy) == (now - timedelta(hours=4), now + timedelta(hours=1))
    assert bounds("session", now - timedelta(hours=5), policy) == (None, None)
    assert bounds("session", now + timedelta(hours=1), policy) == (None, None)
    week, reset = bounds("weekly", now, policy)
    assert week.weekday() == reset.weekday() == 1
    assert week.hour == reset.hour == 1
    assert reset - week == timedelta(days=7)
    assert bounds("monthly", now, policy) == (
        datetime(2026, 12, 1, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_physical_admission_counts_archived_failed_usage_and_serializes_capped_calls(db):
    user = UserModel(email="budget-meter@example.test", hashed_password="unused")
    db.add(user)
    await db.flush()
    policy = InferenceBudget(user_id=user.id, session_limit=Decimal("1.00"))
    db.add(policy)
    await db.flush()
    candidate = LLMCall(user_id=user.id)
    await admit_budgeted_call(candidate)
    db.add(candidate)
    await db.flush()
    started = policy.session_started_at
    assert started == candidate.started_at
    with pytest.raises(BudgetUnavailable, match="Another inference"):
        await admit_budgeted_call(LLMCall(user_id=user.id))
    candidate.status = "error"
    candidate.inference_cost = 1.25
    candidate.soft_delete()
    await db.flush()
    with pytest.raises(BudgetUnavailable) as blocked:
        await admit_budgeted_call(LLMCall(user_id=user.id))
    assert blocked.value.detail()["periods"] == ["session"]
    assert policy.session_started_at == started
    session, _, _ = await envelopes(user.id, policy, datetime.now(timezone.utc))
    assert session.spent == Decimal("1.25")


@pytest.mark.asyncio
async def test_credit_expires_at_each_window_boundary_and_unassigned_credit_stays_inactive(db):
    user = UserModel(email="budget-windows@example.com", hashed_password="unused")
    db.add(user)
    await db.flush()
    now = datetime(2027, 1, 31, 23, tzinfo=timezone.utc)
    policy = InferenceBudget(user_id=user.id, session_limit=Decimal(1), weekly_limit=Decimal(1),
                             monthly_limit=Decimal(1), session_started_at=now - timedelta(hours=4))
    db.add(policy)
    await db.flush()
    legacy = InferenceCreditGrant(id=uuid4(), user_id=user.id, period="session", amount=Decimal(9))
    db.add(legacy)
    window_ends: list[datetime] = []
    for period in PERIODS:
        start, end = bounds(period, now, policy)
        assert start is not None and end is not None
        db.add(InferenceCreditGrant(id=uuid4(), user_id=user.id, period=period, amount=Decimal(2), window_start=start))
        window_ends.append(end)
    await db.flush()

    assert [item.granted for item in await envelopes(user.id, policy, now)] == [Decimal(2)] * 3
    for index, end in enumerate(window_ends):
        assert (await envelopes(user.id, policy, end))[index].granted == 0

    policy.session_started_at = datetime.now(timezone.utc) - timedelta(hours=6)
    await db.flush()
    call = LLMCall(user_id=user.id)
    await admit_budgeted_call(call)
    await db.refresh(legacy)
    assert legacy.window_start is None
    assert (await envelopes(user.id, policy, call.started_at))[0].granted == 0


@pytest.mark.asyncio
async def test_workers_cannot_both_admit_a_physical_call_for_a_capped_user(committed_database):
    async with get_db_session() as db:
        user = UserModel(email="budget-parallel@example.com", hashed_password="unused")
        db.add(user)
        await db.flush()
        identity = user.id
        db.add(InferenceBudget(user_id=identity, monthly_limit=Decimal(1)))
        await db.commit()
    ready = asyncio.Event()
    finish = asyncio.Event()

    async def first():
        async with get_db_session() as db:
            call = LLMCall(user_id=identity)
            await admit_budgeted_call(call)
            db.add(call)
            await db.flush()
            ready.set()
            await finish.wait()
            await db.commit()

    async def second():
        async with get_db_session():
            with pytest.raises(BudgetUnavailable, match="Another inference"):
                await admit_budgeted_call(LLMCall(user_id=identity))

    async with asyncio.timeout(10), asyncio.TaskGroup() as workers:
        workers.create_task(first())
        await ready.wait()
        workers.create_task(second())
        finish.set()


@pytest.mark.asyncio
async def test_credit_flow_requires_active_web_session_and_current_team_manager(client):
    password = "Budget-test-Password-927"
    admin = {"email": "budget-admin@example.com", "password": password}
    member = {"email": "budget-member@example.com", "password": password}
    outsider = {"email": "budget-outsider@example.com", "password": password}

    async def login(credentials):
        client.cookies.clear()
        response = await client.post("/api/auth/login-json", json=credentials)
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    assert (await client.post("/api/auth/register", json=admin)).status_code == 201
    admin_headers = await login(admin)
    member_record = await client.post("/api/auth/users", headers=admin_headers, json=member)
    assert member_record.status_code == 201, member_record.text
    user_id = member_record.json()["id"]
    assert (await client.post("/api/auth/users", headers=admin_headers, json=outsider)).status_code == 201
    url = "/api/llm-budget"
    admin_id = (await client.get(url + "/me", headers=admin_headers)).json()["account"]["user_id"]
    assert (await client.get(url + "/me")).status_code == 401
    legacy = create_access_token({"sub": admin["email"], "user_id": admin_id})
    assert (await client.get(url + "/me", headers={"Authorization": f"Bearer {legacy}"})).status_code == 403
    member_headers = await login(member)
    before = (await client.get(url + "/me", headers=member_headers)).json()
    assert not before["can_request_credit"] and not before["can_configure_own"]
    assert "weekly_reset_hour" not in before["account"]
    assert all(row["limit"] is None for row in before["account"]["envelopes"])
    limits = {"session_limit": "0", "weekly_limit": None, "monthly_limit": "10.00"}
    assert (await client.put(f"{url}/policies/{user_id}", headers=member_headers, json=limits)).status_code == 403
    response = await client.put(f"{url}/policies/{user_id}", headers=admin_headers, json=limits)
    assert response.status_code == 204, response.text
    assert (await client.put(f"{url}/policies/{user_id}", headers=admin_headers,
                             json={**limits, "weekly_reset_hour": 1})).status_code == 422
    assert (await client.put(f"{url}/policies/{user_id}", headers=admin_headers,
                             json={**limits, "referrer_user_id": admin_id})).status_code == 422
    team_response = await client.post("/api/teams", headers=admin_headers,
                                      json={"name": "Budget team", "manager_user_id": admin_id})
    assert team_response.status_code == 201, team_response.text
    team_id = team_response.json()["id"]
    assert (await client.put(f"/api/teams/{team_id}/humans/{user_id}", headers=admin_headers,
                             json={"present": True})).status_code == 204

    async with get_db_session() as db:
        policy = await db.get(InferenceBudget, user_id)
        assert policy is not None
        policy.weekly_reset_hour = 25
        for email, privilege in ((member["email"], "LLM_BUDGET_EDIT_OWN"), (outsider["email"], "UPDATE_USER")):
            account = (await db.scalars(select(UserModel).where(UserModel.email == email))).one()
            code = (await db.scalars(select(Privilege).where(Privilege.code == privilege))).one()
            role = Role(code=f"budget-test-{privilege}", privileges=[code])
            db.add(role)
            await db.flush()
            db.add(Assignment(user_id=account.id, role_id=role.id))
    member_headers = await login(member)
    overview = (await client.get(url + "/me", headers=member_headers)).json()
    assert overview["can_configure_own"] and overview["can_request_credit"]
    assert (await client.get(url + "/managed?configure=true", headers=member_headers)).status_code == 403
    assert (await client.put(f"{url}/policies/{admin_id}", headers=member_headers, json=limits)).status_code == 403
    response = await client.put(f"{url}/policies/{user_id}", headers=member_headers,
                                json={**limits, "monthly_limit": "11.25"})
    assert response.status_code == 204, response.text
    own_account = (await client.get(url + "/me", headers=member_headers)).json()["account"]
    assert Decimal(own_account["envelopes"][2]["limit"]) == Decimal("11.25")
    weekly_reset = datetime.fromisoformat(own_account["envelopes"][1]["resets_at"])
    assert (weekly_reset.weekday(), weekly_reset.hour) == (1, 1)

    payload = {"period": "session", "amount": "2.50"}
    first = await client.post(url + "/requests", headers=member_headers, json=payload)
    second = await client.post(url + "/requests", headers=member_headers, json=payload)
    assert first.status_code == second.status_code == 201
    identity = first.json()["id"]
    assert identity == second.json()["id"]
    review = f"{url}/requests/{identity}/review"
    approval = {"decision": "approved"}
    outsider_headers = await login(outsider)
    assert (await client.get(url + "/managed", headers=outsider_headers)).json()["total"] == 0
    outside = (await client.get(url + "/me", headers=outsider_headers)).json()
    assert not outside["can_configure_own"]
    assert (await client.put(f"{url}/policies/{outside['account']['user_id']}", headers=outsider_headers,
                             json=limits)).status_code == 403
    assert (await client.post(review, headers=outsider_headers, json=approval)).status_code == 404
    token = await client.post("/api/auth/me/tokens", headers=admin_headers, json={"label": "Budget API test"})
    assert token.status_code == 201, token.text
    machine = {"Authorization": "Bearer " + token.json()["token"], "Origin": str(client.base_url)}
    assert (await client.get(url + "/me", headers=machine)).status_code == 403
    assert (await client.post(review, headers=machine, json=approval)).status_code == 403
    assert (await client.put(f"{url}/policies/{user_id}", headers=machine, json=limits)).status_code == 403
    manager_url = f"/api/teams/{team_id}/manager"
    assert (await client.put(manager_url, headers=machine, json={"user_id": user_id})).status_code == 403
    assert (await client.put(f"/api/teams/{team_id}/humans/{user_id}", headers=machine,
                             json={"present": False})).status_code == 403
    assert (await client.put(f"/api/teams/{team_id}/humans/{admin_id}", headers=admin_headers,
                             json={"present": False})).status_code == 409
    grant_url = f"{url}/grants/{user_id}"
    session_grant = {"operation_id": str(uuid4()), "period": "session", "amount": "1"}
    assert (await client.post(grant_url, headers=admin_headers, json=session_grant)).status_code == 409
    assert (await client.post(review, headers=admin_headers, json=approval)).status_code == 409
    state = (await client.get(url + "/me", headers=member_headers)).json()["account"]
    assert state["requests"][0]["status"] == "pending"
    assert Decimal(state["envelopes"][0]["granted"]) == 0

    async with get_db_session() as db:
        policy = await db.get(InferenceBudget, user_id)
        assert policy is not None
        policy.session_started_at = datetime.now(timezone.utc)
    assert (await client.post(review, headers=admin_headers, json=approval)).status_code == 204
    assert (await client.post(review, headers=admin_headers, json=approval)).status_code == 204
    state = (await client.get(url + "/me", headers=member_headers)).json()["account"]
    assert Decimal(state["envelopes"][0]["granted"]) == Decimal("2.50")
    assert not state["envelopes"][0]["exhausted"]
    assert (await client.post(grant_url, headers=admin_headers, json=session_grant)).status_code == 204
    async with get_db_session() as db:
        policy = await db.get(InferenceBudget, user_id)
        assert policy is not None
        policy.session_started_at = datetime.now(timezone.utc) - timedelta(hours=5)
    assert (await client.post(grant_url, headers=admin_headers, json=session_grant)).status_code == 204
    assert (await client.post(grant_url, headers=admin_headers,
                              json={**session_grant, "operation_id": str(uuid4())})).status_code == 409
    state = (await client.get(url + "/me", headers=member_headers)).json()["account"]
    assert Decimal(state["envelopes"][0]["granted"]) == 0
    grant = {"operation_id": str(uuid4()), "period": "monthly", "amount": "3"}
    assert (await client.post(f"{url}/grants/{user_id}", headers=member_headers, json=grant)).status_code == 404
    assert (await client.post(f"{url}/grants/{user_id}", headers=machine, json=grant)).status_code == 403
    assert (await client.post(f"{url}/grants/{user_id}", headers=admin_headers, json=grant)).status_code == 204
    outsider_id = outside["account"]["user_id"]
    all_accounts = await client.get(url + "/managed", headers=admin_headers)
    assert {row["user_id"] for row in all_accounts.json()["items"]} == {user_id, outsider_id}
    assert (await client.put(manager_url, headers=admin_headers, json={"user_id": outsider_id})).status_code == 422
    assert (await client.put(manager_url, headers=admin_headers, json={"user_id": user_id})).status_code == 204
    for _ in range(2):
        other = await client.post("/api/teams", headers=admin_headers,
                                  json={"name": "Another budget team", "manager_user_id": user_id})
        assert other.status_code == 201, other.text
        other_team_id = other.json()["id"]
        assert (await client.put(f"/api/teams/{other_team_id}/humans/{outsider_id}", headers=admin_headers,
                                 json={"present": True})).status_code == 204
    managed = (await client.get(url + "/managed", headers=member_headers)).json()
    assert managed["total"] == 2
    assert {row["user_id"] for row in managed["items"]} == {admin_id, outsider_id}
    assert all(row["can_configure"] and row["can_manage_credits"] for row in managed["items"])
    assert (await client.put(f"{url}/policies/{outsider_id}", headers=member_headers, json=limits)).status_code == 204
    assert (await client.put(f"{url}/policies/{user_id}", headers=outsider_headers, json=limits)).status_code == 403
    assert (await client.post(f"{url}/grants/{user_id}", headers=admin_headers, json=grant)).status_code == 404
    assert (await client.post(f"{url}/grants/{outsider_id}", headers=admin_headers, json=grant)).status_code == 404
    revoked = await login(admin)
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.get(url + "/me", headers=revoked)).status_code == 401
