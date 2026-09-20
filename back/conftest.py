"""Shared backend fixtures with hard database-isolation guarantees."""

from typing import Any, AsyncIterator
from uuid import uuid4

import pytest_asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.runtime_isolation import isolated_api_import

with isolated_api_import():
    from main import app
from core.database import engine
from core.database import database as database_module
from core.database.database import db_session_ctx
from core.settings import settings


@pytest.fixture(autouse=True)
def isolated_internal_secrets(monkeypatch, tmp_path_factory):
    """Unit/HTTP clients do not run lifespan; provide isolated test credentials."""
    import core.secrets as internal
    from core.params import web_push

    monkeypatch.setattr(internal, "_auth_secret_key", "isolated-unit-tests-signing-secret-0001")
    monkeypatch.setattr(web_push, "_keys", None)
    # Keep this outside each test's storage root, notably quota scenarios.
    browser_token = tmp_path_factory.mktemp("internal-secrets") / "browser-token"
    browser_token.write_text("isolated-tests-browser-token-0001")
    monkeypatch.setattr(internal, "BROWSER_TOKEN_PATH", browser_token)


async def _load_internal_test_secrets(session: AsyncSession) -> None:
    """Hydrate the generated baseline identity for tests that use the database."""
    from sqlalchemy import select
    from core.params.consts import Params
    from core.params.models import Param
    from core.params.params_service import reveal
    from core.params.web_push import load_web_push_keys
    from core.secrets import load_auth_secret_key

    for name, loader in ((Params.AUTH_SECRET_KEY, load_auth_secret_key), (Params.WEB_PUSH_VAPID_KEYS, load_web_push_keys)):
        value = await session.scalar(select(Param.value).where(Param.name == name))
        loader(reveal(name, value) or "")


@pytest.fixture(autouse=True)
def isolate_subscription_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each isolated database starts with an unloaded application confirmation flag."""
    from app.llm import subscription_policy

    monkeypatch.setattr(subscription_policy, "_chatgpt_acknowledged", None)


@pytest.fixture(autouse=True)
def isolate_http_quotas(monkeypatch):
    """Unrelated scenarios do not share quotas; rate-limit tests enable them."""
    from core.rate_limit import limiter

    monkeypatch.setattr(limiter, "enabled", False)


def _supply_legacy_agent_fixture_manager(
    session: Session,
    _flush_context: Any,
    _instances: Any,
) -> None:
    """Give raw legacy Agent fixtures a valid manager inside tests only.

    Production creates agents through ``agent_service``, which resolves the
    authenticated creator. Many unrelated DB tests build ORM rows directly;
    keeping their setup centralized avoids coupling every domain test to user
    creation while preserving the real ``NOT NULL``/foreign-key constraint.
    """
    from app.agent.models import Agent
    from core.user import UserModel

    agents = [
        entity
        for entity in session.new
        if isinstance(entity, Agent)
        and entity.user_id is None
        and entity.user is None
    ]
    if not agents:
        return

    manager = session.info.get("legacy_agent_fixture_manager")
    if not isinstance(manager, UserModel):
        manager = UserModel(
            email=f"agent-fixture-{id(session)}@example.test",
            hashed_password="not-used",
            display_name="Agent fixture manager",
            is_active=True,
        )
        session.info["legacy_agent_fixture_manager"] = manager
        session.add(manager)

    for agent in agents:
        agent.user = manager


def pytest_sessionstart() -> None:
    """Refuse to run a suite that could persist data in a live environment."""

    if settings.APP_ENV != "test" or settings.POSTGRES_DB != "test_db":
        raise RuntimeError(
            "Backend tests require APP_ENV=test and POSTGRES_DB=test_db. "
            "Run them with `make tests`; the development database is protected."
        )


@pytest_asyncio.fixture(autouse=True)
async def close_application_pool() -> AsyncIterator[None]:
    """Close connections before their test's event loop is destroyed.

    A service can open a managed session even in a test without ``db`` or
    ``client``. Disposing only in those fixtures leaves its pooled connections
    attached to a closed loop, so asyncpg cannot await cancellation during GC.
    """
    try:
        yield
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db() -> AsyncIterator[AsyncSession]:
    """Roll back every database change, including service-level commits."""

    # pytest-asyncio strict creates one loop per test. Replace any pool inherited from a
    # previous loop before checkout; trying to ping one of its asyncpg connections fails before
    # this isolation fixture can take ownership of the session.
    await engine.dispose(close=False)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        original_factory = database_module.AsyncSessionLocal

        def isolated_session_factory() -> AsyncSession:
            return AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )

        database_module.AsyncSessionLocal = isolated_session_factory  # type: ignore[assignment]
        from app.llm import llm_call_service

        original_llm_factory = llm_call_service.AsyncSessionLocal
        llm_call_service.AsyncSessionLocal = isolated_session_factory  # type: ignore[assignment]
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        token = db_session_ctx.set(session)
        event.listen(Session, "before_flush", _supply_legacy_agent_fixture_manager)
        try:
            await _load_internal_test_secrets(session)
            yield session
        finally:
            event.remove(Session, "before_flush", _supply_legacy_agent_fixture_manager)
            db_session_ctx.reset(token)
            await session.close()
            database_module.AsyncSessionLocal = original_factory
            llm_call_service.AsyncSessionLocal = original_llm_factory
            if transaction.is_active:
                await transaction.rollback()
    # pytest-asyncio strict creates a loop per test. Pooled asyncpg connections
    # cannot be reused from the next loop.
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(committed_database) -> AsyncIterator[AsyncClient]:
    """Provide an ASGI client whose request commits remain rollback-only."""

    await engine.dispose(close=False)
    from core.database import middleware as database_middleware

    async with committed_database.kw["bind"].connect() as connection:
        transaction = await connection.begin()
        original_database_factory = database_module.AsyncSessionLocal
        original_factory = database_middleware.AsyncSessionLocal

        def isolated_session_factory() -> AsyncSession:
            return AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )

        database_middleware.AsyncSessionLocal = isolated_session_factory  # type: ignore[assignment]
        database_module.AsyncSessionLocal = isolated_session_factory  # type: ignore[assignment]
        from app.llm import llm_call_service

        original_llm_factory = llm_call_service.AsyncSessionLocal
        llm_call_service.AsyncSessionLocal = isolated_session_factory  # type: ignore[assignment]
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://localhost") as http:
                yield http
        finally:
            database_middleware.AsyncSessionLocal = original_factory
            database_module.AsyncSessionLocal = original_database_factory
            llm_call_service.AsyncSessionLocal = original_llm_factory
            if transaction.is_active:
                await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def committed_database(monkeypatch):
    """Clone the ephemeral baseline; use independent connections and real commits.

    Unlike the rollback fixture, this exercises row locks and transaction
    visibility across workers. Only this fixture's uniquely named DB is dropped.
    """
    assert settings.APP_ENV == "test" and settings.POSTGRES_DB == "test_db"
    name = f"test_concurrency_{uuid4().hex}"
    url = database_module.engine.url
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    isolated = create_async_engine(url.set(database=name))
    created = False
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE test_template'))
            created = True
        factory = async_sessionmaker(isolated, expire_on_commit=False)
        monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
        async with factory() as session:
            await _load_internal_test_secrets(session)
        yield factory
    finally:
        await isolated.dispose()
        if created:
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest_asyncio.fixture
async def inference_db(committed_database, monkeypatch):
    """A committed session for workflows invoking autonomous inference workers."""
    from app.llm import llm_call_service
    from app.llm.facade import stop_inference_worker
    from core.database import get_db_session

    monkeypatch.setattr(llm_call_service, "AsyncSessionLocal", committed_database)
    event.listen(Session, "before_flush", _supply_legacy_agent_fixture_manager)
    try:
        async with get_db_session() as session:
            try:
                yield session
            finally:
                await stop_inference_worker()
    finally:
        event.remove(Session, "before_flush", _supply_legacy_agent_fixture_manager)
