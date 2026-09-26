"""Repeated checks stay cheap without retaining revoked or cross-context rights."""

import asyncio
from contextlib import contextmanager

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, update
from sqlalchemy.engine import Engine

from core.authorize import check_privilege, request_privilege_cache, role_id_ctx
from core.authorize.models import Assignment, Privilege, Role, RolePrivilege
from core.user.models import User


@pytest_asyncio.fixture
async def grants(db):
    user = User(email="cache-owner@example.test", hashed_password="unused", is_active=True)
    other = User(email="cache-other@example.test", hashed_password="unused", is_active=True)
    privilege = Privilege(code="CACHE_READ")
    role = Role(code="cache-reader", privileges=[privilege])
    empty = Role(code="cache-empty", privileges=[])
    db.add_all([user, other, role, empty])
    await db.flush()
    assignment = Assignment(user_id=user.id, role_id=role.id)
    db.add_all([assignment, Assignment(user_id=user.id, role_id=empty.id)])
    await db.commit()
    return user, other, role, empty, privilege, assignment


@contextmanager
def select_count():
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", record)


@pytest.mark.asyncio
async def test_repeated_checks_are_isolated_by_user_and_active_role(db, grants):
    user, other, role, empty, *_ = grants
    with request_privilege_cache(), select_count() as statements:
        token = role_id_ctx.set(role.id)
        try:
            assert await check_privilege(user, ["MISSING", "CACHE_READ"], db)
            assert not await check_privilege(user, "MISSING", db)
            assert await check_privilege(user, "CACHE_READ", db)
            assert len(statements) == 1

            role_id_ctx.set(empty.id)
            assert not await check_privilege(user, "CACHE_READ", db)
            assert not await check_privilege(other, "CACHE_READ", db, role.id)
            role_id_ctx.set(role.id)
            assert await check_privilege(user, "CACHE_READ", db)
            assert len(statements) == 3

            # Special rights need neither roles nor a database read.
            assert await check_privilege(user, "user", db)
            assert await check_privilege(None, ["guest", "MISSING"], db)
            assert not await check_privilege(None, "user", db)
            assert not await check_privilege(user, [], db)
            assert len(statements) == 3
            user.is_active = False
            assert not await check_privilege(user, ["user", "CACHE_READ"], db)
        finally:
            role_id_ctx.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["relationship", "bulk_grant", "soft_delete", "assignment"])
async def test_writes_invalidate_warm_permissions_before_commit(db, grants, mutation):
    user, _, role, empty, privilege, assignment = grants
    with request_privilege_cache():
        assert await check_privilege(user, "CACHE_READ", db, role.id)
        if mutation == "relationship":
            # Pending ORM changes must trigger autoflush despite a cache hit.
            role.privileges.remove(privilege)
        elif mutation == "bulk_grant":
            await db.execute(delete(RolePrivilege).where(RolePrivilege.role_id == role.id))
        elif mutation == "soft_delete":
            assignment.soft_delete()
        else:
            await db.execute(
                update(Assignment).where(Assignment.id == assignment.id).values(user_id=grants[1].id)
            )
        assert not await check_privilege(user, "CACHE_READ", db, role.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["commit", "rollback", "savepoint"])
async def test_transaction_boundaries_drop_cached_denials_and_grants(db, grants, finish):
    user, _, role, _, privilege, _ = grants
    with request_privilege_cache():
        assert await check_privilege(user, "CACHE_READ", db, role.id)
        nested = await db.begin_nested() if finish == "savepoint" else None
        await db.execute(delete(RolePrivilege).where(RolePrivilege.role_id == role.id))
        assert not await check_privilege(user, "CACHE_READ", db, role.id)
        if finish == "commit":
            await db.commit()
            db.add(RolePrivilege(role_id=role.id, privilege_id=privilege.id))
            await db.commit()
        elif nested is not None:
            await nested.rollback()
        else:
            await db.rollback()
            await db.refresh(user)
            await db.refresh(role)
        assert await check_privilege(user, "CACHE_READ", db, role.id)


@pytest.mark.asyncio
async def test_cache_ends_with_request_even_for_inherited_background_context(db, grants):
    user, _, role, *_ = grants
    proceed = asyncio.Event()

    async def inherited_check():
        await proceed.wait()
        return await check_privilege(user, "CACHE_READ", db, role.id)

    with select_count() as statements:
        with pytest.raises(ValueError), request_privilege_cache():
            assert await check_privilege(user, "CACHE_READ", db, role.id)
            task = asyncio.create_task(inherited_check())
            raise ValueError("request failed")
        proceed.set()
        assert await task
        assert await check_privilege(user, "CACHE_READ", db, role.id)
        with request_privilege_cache():
            assert await check_privilege(user, "CACHE_READ", db, role.id)
        assert len(statements) == 4


@pytest.mark.asyncio
async def test_revocation_from_another_session_is_visible_on_next_request(committed_database):
    async with committed_database() as writer:
        user = User(email="cache-revocation@example.test", hashed_password="unused", is_active=True)
        role = Role(code="cache-revocation", privileges=[Privilege(code="CACHE_REVOKE")])
        writer.add_all([user, role])
        await writer.flush()
        writer.add(Assignment(user_id=user.id, role_id=role.id))
        await writer.commit()
        async with committed_database() as reader:
            with request_privilege_cache():
                assert await check_privilege(user, "CACHE_REVOKE", reader, role.id)
                await writer.execute(delete(RolePrivilege).where(RolePrivilege.role_id == role.id))
                await writer.commit()
                # Even inside one request, a second SQL session has its own view.
                assert not await check_privilege(user, "CACHE_REVOKE", writer, role.id)
            with request_privilege_cache():
                assert not await check_privilege(user, "CACHE_REVOKE", reader, role.id)
