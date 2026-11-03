"""Finish legacy profile conversion before removing its format columns."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.util import RichTextError, convert_legacy_to_html


def needs_conversion(transitions: SchemaTransitionSet) -> bool:
    return "agents.profile_media_type" in transitions.removed_columns


async def retirement_ready(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    row = (await session.execute(text("""
        SELECT column_default FROM information_schema.columns
        WHERE table_schema='public' AND table_name='agents' AND column_name='profile_media_type'
    """))).one_or_none()
    return row is None or row[0] in {"'text/html'::character varying", "'text/html'::text"}


async def prepare_retirement(session: AsyncSession, transitions: SchemaTransitionSet) -> None:
    if not await retirement_ready(session, transitions):
        # A staged application no longer supplies this retired field. Its old
        # Markdown default would cause new HTML profiles to be converted twice.
        await session.execute(text("ALTER TABLE public.agents ALTER COLUMN profile_media_type SET DEFAULT 'text/html'"))


async def complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    exists = await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'agents' AND column_name = 'profile_media_type')
    """))
    if not exists:
        return True
    return not bool(await session.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM agents WHERE profile_media_type IS DISTINCT FROM 'text/html')"
    )))


async def convert_batch(session: AsyncSession, _transitions: SchemaTransitionSet) -> None:
    rows = (await session.execute(text("""
        SELECT id, personality, job_description, profile_media_type FROM agents
        WHERE profile_media_type IS DISTINCT FROM 'text/html'
        ORDER BY id LIMIT 500 FOR UPDATE
    """))).mappings()
    for row in rows:
        converted: dict[str, object] = {"id": row["id"]}
        for key in ("personality", "job_description"):
            value = row[key]
            try:
                converted[key] = convert_legacy_to_html(value, row["profile_media_type"] or "text/markdown")[0] if value is not None else None
            except RichTextError as exc:
                raise ValueError(
                    f"Cannot convert legacy Agent profile: agent={row['id']} field={key} "
                    f"format={row['profile_media_type']!r}: {exc}"
                ) from exc
        await session.execute(text("""
            UPDATE agents SET personality = :personality, job_description = :job_description,
                profile_media_type = 'text/html' WHERE id = :id
        """), converted)


def register_html_conversion(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.agent.prepare_profile_retirement", phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="new-profiles-remain-html-until-format-column-retirement-v1",
        predicate=needs_conversion, handler=prepare_retirement, postcondition=retirement_ready,
    ))
    registry.register_action(DbAdminAction(
        key="app.agent.editorial_html", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="html-profile-retire-format-and-source",
        compatible_checksums=frozenset({"html-profile-1-preserve-source"}),
        predicate=needs_conversion, handler=convert_batch, postcondition=complete,
    ))
