"""Public signup never grants administration to a subsequent account."""

import asyncio

import pytest
from sqlalchemy import func, select

from core.authorize.models import Assignment, Role
from core.database import get_db_session
from core.database.database import db_session_ctx
from core.params import runtime_settings
from core.user import user_service
from core.user.models import User
from core.user.schemas import UserRegistration


@pytest.mark.asyncio
async def test_an_inactive_account_still_closes_bootstrap(client):
    async with get_db_session() as db:
        db.add(User(email="inactive@example.com", hashed_password="unused", is_active=False))
        await db.flush()
    assert (await client.get('/api/auth/registration-status')).json() == {'registration_open': False, 'initial_admin_required': False}
    response = await client.post('/api/auth/register', json={
        'email': 'visitor@example.com', 'password': 'Visitor-password-123',
    })
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize('open_signup', [False, True])
async def test_concurrent_signup_creates_only_one_administrator(committed_database, monkeypatch, open_signup):
    monkeypatch.setattr(runtime_settings, 'ALLOW_USER_REGISTRATION', open_signup)

    async def signup(index):
        async with committed_database() as db:
            token = db_session_ctx.set(db)
            try:
                return await user_service.register_public_user(UserRegistration(
                    email=f'concurrent-{index}@example.com', password='Concurrent-password-123',
                ))
            finally:
                db_session_ctx.reset(token)

    results = await asyncio.gather(signup(1), signup(2), return_exceptions=True)
    assert sum(isinstance(result, User) for result in results) == (2 if open_signup else 1)
    assert sum(isinstance(result, user_service.RegistrationClosedError) for result in results) == (0 if open_signup else 1)
    async with committed_database() as db:
        administrators = await db.scalar(select(func.count(Assignment.id)).join(Role).where(Role.code == 'admin'))
        assert administrators == 1
