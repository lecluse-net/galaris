import asyncio
import json
from typing import Any, AsyncGenerator, cast
from contextvars import ContextVar
from contextlib import asynccontextmanager
from loguru import logger
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from core import settings
from .pool import ObservedAsyncPool


def _strip_json_nul_characters(value: Any) -> Any:
    """Remove NUL characters that PostgreSQL cannot store inside JSON values."""

    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {
            _strip_json_nul_characters(key): _strip_json_nul_characters(item)
            for key, item in cast(dict[Any, Any], value).items()
        }
    if isinstance(value, list):
        return [
            _strip_json_nul_characters(item)
            for item in cast(list[Any], value)
        ]
    if isinstance(value, tuple):
        return tuple(
            _strip_json_nul_characters(item)
            for item in cast(tuple[Any, ...], value)
        )
    return value


def serialize_json_for_postgresql(value: Any) -> str:
    """Serialize JSON after enforcing PostgreSQL's text encoding constraint.

    PostgreSQL rejects ``\\u0000`` while decoding JSON/JSONB strings, even though the
    sequence is valid JSON. Values persisted from external tools and model output are
    dynamic at this boundary, so normalize their nested strings before SQLAlchemy hands
    the encoded payload to asyncpg.
    """

    return json.dumps(_strip_json_nul_characters(value))


engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=ObservedAsyncPool,
    echo=(settings.LOG_LEVEL == "DEBUG"),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    json_serializer=serialize_json_for_postgresql,
    connect_args={
        "timeout": 10,
        "server_settings": {
            "statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS),
            "lock_timeout": str(settings.DB_LOCK_TIMEOUT_MS),
        },
    },
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

# Context variable to store the current database session
db_session_ctx: ContextVar[AsyncSession] = ContextVar("db_session")


def get_db() -> AsyncSession:
    """Return the current session or fail outside a managed database context."""
    try:
        return db_session_ctx.get()
    except LookupError:
        raise RuntimeError(
            "No database session exists in the current context. Use a managed FastAPI or CLI context."
        )


async def release_db_transaction() -> bool:
    """Commit the contextual transaction when one exists.

    Long-running runtimes call this after their database-backed setup and before
    starting concurrent work. The session remains contextual for sequential caller
    code, while the commit returns its checked-out connection to the pool. Runtime
    branches that access the database must still open their own managed sessions.

    Return ``False`` for deliberately database-free entry points such as isolated
    harness tests.
    """

    try:
        session = db_session_ctx.get()
    except LookupError:
        return False
    await session.commit()
    return True


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Open a session, commit on success, roll back on failure,
    and ContextVar cleanup automatically.

    Prefer ``get_db()`` in application code. Use this context manager at CLI and
    infrastructure orchestration boundaries such as ``core.dbadmin``.

    """
    async with AsyncSessionLocal() as session:
        token = db_session_ctx.set(session)
        try:
            # Yield control to the script's async-with block.
            yield session

            # Commit when the command completes successfully.
            await session.commit()
        except Exception:
            # Roll back everything when the script raises.
            await session.rollback()
            raise
        finally:
            # Always clear the context.
            db_session_ctx.reset(token)


async def wait_for_db(
    *,
    timeout: float = 60.0,
    initial_delay: float = 0.5,
    max_delay: float = 5.0,
) -> None:
    """Wait until the database is reachable before application startup.

    DNS startup, database restart, or a brief network outage can make a remote
    database temporarily unreachable. Without this wait, the first lifespan query
    terminates Uvicorn without retrying.

    Ping with ``SELECT 1`` and bounded exponential backoff until ``timeout``.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    delay = initial_delay
    attempt = 0
    while True:
        attempt += 1
        try:
            # Pool acquisition, connection, ping and context cleanup all consume
            # the same deadline; a last retry must not get a fresh SQL timeout.
            async with asyncio.timeout_at(deadline):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            if attempt > 1:
                logger.info("Database reachable after {} attempt(s)", attempt)
            return
        except Exception as exc:
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.error(
                    "Database unreachable after {} attempt(s) / {:.0f}s: {}",
                    attempt,
                    timeout,
                    exc,
                )
                raise
            sleep_for = min(delay, max_delay, remaining)
            logger.warning(
                "Database unreachable (attempt {}): {}; retrying in {:.1f}s",
                attempt,
                exc,
                sleep_for,
            )
            await asyncio.sleep(sleep_for)
            delay = min(delay * 2, max_delay)


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base using ``DeclarativeBase``.

    This replaces legacy ``declarative_base()`` so Pylance and Pyright can infer
    model constructors correctly, including models using HistoryMixin.
    """

    metadata = MetaData()
