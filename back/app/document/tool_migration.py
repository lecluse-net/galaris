"""Move existing sharing-function exposure policies to the Document Tool."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet

from .independence import needs_independence

_MAPPING = """(VALUES ('document_share','document_share'),
    ('memory_share','document_share'),('memory_sharing','document_sharing'))"""


async def complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return not bool(await session.scalar(text(f"""SELECT EXISTS (
        SELECT 1 FROM tool_function_state old JOIN tools src ON src.id=old.tool_id AND src.code='memory'
        JOIN {_MAPPING} mapping(old_name,new_name) ON mapping.old_name=old.function_name
        LEFT JOIN tools dst ON dst.code='document'
        LEFT JOIN tool_function_state target ON target.tool_id=dst.id
            AND target.function_name=mapping.new_name AND target.capability_kind=old.capability_kind
        WHERE target.id IS NULL)
        OR EXISTS (
        SELECT 1 FROM connection_function_state old
        JOIN connections origin ON origin.id=old.connection_id
        JOIN tools src ON src.id=origin.tool_id AND src.code='memory'
        JOIN {_MAPPING} mapping(old_name,new_name) ON mapping.old_name=old.function_name
        LEFT JOIN tools dst ON dst.code='document'
        LEFT JOIN connections recipient ON recipient.tool_id=dst.id AND recipient.agent_id=origin.agent_id
        LEFT JOIN connection_function_state target ON target.connection_id=recipient.id
            AND target.function_name=mapping.new_name AND target.capability_kind=old.capability_kind
        WHERE target.id IS NULL)""")))


async def transfer(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    # The canonical Document connection has been seeded by the Tools datasets.
    # Coalescing the retired mutation alias uses the more restrictive explicit
    # state. Existing administrator choices on the new Tool are never replaced.
    for table, reference, origin, target in (
        ("tool_function_state", "tool_id", "src.id", "dst.id"),
        ("connection_function_state", "connection_id", "origin.id", "recipient.id"),
    ):
        joins = "" if reference == "tool_id" else "JOIN connections origin ON origin.tool_id=src.id JOIN connections recipient ON recipient.tool_id=dst.id AND recipient.agent_id=origin.agent_id"
        await session.execute(text(f"""INSERT INTO {table}({reference},function_name,capability_kind,enabled,state)
            SELECT {target},mapping.new_name,old.capability_kind,
                max(CASE coalesce(old.state,CASE WHEN old.enabled THEN 'enabled' ELSE 'disabled' END)
                    WHEN 'disabled' THEN 2 WHEN 'ask' THEN 1 ELSE 0 END)=0,
                CASE max(CASE coalesce(old.state,CASE WHEN old.enabled THEN 'enabled' ELSE 'disabled' END)
                    WHEN 'disabled' THEN 2 WHEN 'ask' THEN 1 ELSE 0 END)
                    WHEN 2 THEN 'disabled' WHEN 1 THEN 'ask' ELSE 'enabled' END
            FROM tools src JOIN tools dst ON dst.code='document' {joins}
            JOIN {table} old ON old.{reference}={origin}
            JOIN {_MAPPING} mapping(old_name,new_name) ON mapping.old_name=old.function_name
            WHERE src.code='memory' GROUP BY {target},mapping.new_name,old.capability_kind
            ON CONFLICT ({reference},capability_kind,function_name) DO NOTHING"""))


def register_tool_migration(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.document.sharing_tool_policies", phase=DbAdminPhase.AFTER_DATASET,
        checksum="preserve-sharing-function-states-during-document-tool-split-v1",
        predicate=needs_independence, handler=transfer, postcondition=complete,
    ))
