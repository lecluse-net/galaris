"""Reject schema objects which the current Atlas target cannot represent."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..contracts import DbAdminFatalError


async def validate_supported_objects(connection: AsyncConnection) -> None:
    """Never report full convergence while ignoring user-defined SQL objects.

    Extension members are owned by their extension, not by the application's
    table metadata. Internal constraint triggers are covered by their constraints.
    """
    objects = list(await connection.scalars(text("""
        SELECT 'routine ' || p.oid::regprocedure::text AS object
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND NOT EXISTS (
            SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass
            AND d.objid=p.oid AND d.deptype='e')
        UNION ALL
        SELECT 'trigger ' || c.relname || '.' || t.tgname
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND NOT t.tgisinternal
        AND NOT EXISTS (SELECT 1 FROM pg_depend d
            WHERE d.classid='pg_trigger'::regclass AND d.objid=t.oid AND d.deptype='e')
        UNION ALL
        SELECT 'relation ' || c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('v','m','f','p')
        AND NOT EXISTS (SELECT 1 FROM pg_depend d
            WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
        UNION ALL
        SELECT 'policy ' || c.relname || '.' || p.polname
        FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
        ORDER BY object LIMIT 50
    """)))
    if objects:
        raise DbAdminFatalError(
            "Cannot verify complete public schema: SQL objects are absent from the declared "
            "Atlas target: " + ", ".join(objects)
        )
