"""Freeze the clean DbAdmin test baseline before any test opens a connection."""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.database.database import engine
from core.settings import settings


async def main():
    assert settings.APP_ENV == "test" and settings.POSTGRES_DB == "test_db"
    admin = create_async_engine(engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.execute(text("CREATE DATABASE test_template TEMPLATE test_db"))
    finally:
        await admin.dispose()


if __name__ == "__main__":
    asyncio.run(main())
