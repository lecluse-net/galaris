"""Real PostgreSQL upgrade guarantees beyond a fresh, superuser-owned schema."""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import text

from core.database import engine
from core.dbadmin import DbAdminEnumMapping, DbAdminFatalError, DbAdminRegistry
from core.dbadmin.contracts import EnumTransition
from core.dbadmin._internal.enums import prepare_enum_transitions


@pytest_asyncio.fixture
async def connection():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


def registry(name="safety_state"):
    result = DbAdminRegistry()
    result.register_enum_mapping(DbAdminEnumMapping(name, {"old": "new"}))
    return result


def transition(name="safety_state"):
    return EnumTransition(name, ("open", "old"), ("open", "new"))


async def setup(connection):
    await connection.execute(text("CREATE TYPE public.safety_state AS ENUM ('open', 'old')"))
    await connection.execute(text("CREATE TABLE public.safety_rows (state public.safety_state DEFAULT 'old')"))
    await connection.execute(text("INSERT INTO public.safety_rows DEFAULT VALUES"))


@pytest.mark.asyncio
async def test_replacement_preserves_defaults_privileges_owner_and_replay(connection):
    await setup(connection)
    await connection.execute(text("CREATE ROLE safety_owner NOLOGIN"))
    await connection.execute(text("CREATE ROLE safety_reader NOLOGIN"))
    await connection.execute(text("ALTER TYPE public.safety_state OWNER TO safety_owner"))
    await connection.execute(text("SET LOCAL ROLE safety_owner"))
    await connection.execute(text("REVOKE USAGE ON TYPE public.safety_state FROM PUBLIC"))
    await connection.execute(text("GRANT USAGE ON TYPE public.safety_state TO safety_reader WITH GRANT OPTION"))
    await connection.execute(text("COMMENT ON TYPE public.safety_state IS 'Synthetic state'"))
    await connection.execute(text("RESET ROLE"))
    before = (await connection.execute(text(
        "SELECT pg_get_userbyid(typowner), typacl::text, obj_description(oid, 'pg_type') "
        "FROM pg_type WHERE typname='safety_state' AND typnamespace='public'::regnamespace"
    ))).one()
    await prepare_enum_transitions(connection, (transition(),), registry())
    # The default must already work before Atlas (or a failure in the next phase).
    await connection.execute(text("INSERT INTO public.safety_rows DEFAULT VALUES"))
    await prepare_enum_transitions(connection, (transition(),), registry())
    assert (await connection.execute(text("SELECT state::text FROM public.safety_rows"))).scalars().all() == ["new", "new"]
    after = (await connection.execute(text(
        "SELECT pg_get_userbyid(typowner), typacl::text, obj_description(oid, 'pg_type') "
        "FROM pg_type WHERE typname='safety_state' AND typnamespace='public'::regnamespace"
    ))).one()
    assert after == before


@pytest.mark.asyncio
async def test_stale_snapshot_cannot_silently_null_an_unexpected_label(connection):
    await connection.execute(text("CREATE TYPE public.safety_state AS ENUM ('open', 'old', 'unexpected')"))
    await connection.execute(text("CREATE TABLE public.safety_rows (state public.safety_state)"))
    await connection.execute(text("INSERT INTO public.safety_rows VALUES ('unexpected')"))
    with pytest.raises(DbAdminFatalError, match="changed since inspection"):
        await prepare_enum_transitions(connection, (transition(),), registry())
    assert await connection.scalar(text("SELECT state::text FROM public.safety_rows")) == "unexpected"


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency", [
    "CREATE VIEW public.safety_view AS SELECT state FROM public.safety_rows",
    "ALTER TABLE public.safety_rows ADD CHECK (state <> 'open'::public.safety_state)",
    "CREATE TABLE public.safety_arrays (states public.safety_state[])",
    "CREATE FUNCTION public.safety_fn() RETURNS public.safety_state LANGUAGE sql AS $$ SELECT 'old'::public.safety_state $$",
    "CREATE INDEX safety_partial ON public.safety_rows(state) WHERE state IS NOT NULL",
    "ALTER TABLE public.safety_rows ALTER COLUMN state SET DEFAULT (('o'::text || 'ld'::text)::public.safety_state)",
    "ALTER TABLE public.safety_rows ADD COLUMN label text GENERATED ALWAYS AS (CASE WHEN state IS NULL THEN 'empty' ELSE 'set' END) STORED",
    "CREATE DOMAIN public.safety_domain AS public.safety_state",
    "CREATE TABLE public.safety_child () INHERITS (public.safety_rows)",
    "CREATE TABLE pg_temp.safety_external (state public.safety_state)",
    "CREATE TABLE public.safety_partitioned (state public.safety_state) PARTITION BY LIST (state)",
    "ALTER TABLE public.safety_rows ADD UNIQUE (state), ADD FOREIGN KEY (state) REFERENCES public.safety_rows (state)",
])
async def test_unsupported_dependencies_fail_without_poisoning_transaction(connection, dependency):
    await setup(connection)
    await connection.execute(text(dependency))
    with pytest.raises(DbAdminFatalError, match="dependency"):
        await prepare_enum_transitions(connection, (transition(),), registry())
    assert await connection.scalar(text("SELECT state::text FROM public.safety_rows")) == "old"


@pytest.mark.asyncio
async def test_long_enum_name_and_shadow_schema_do_not_redirect_ddl(connection):
    name = "safety_" + "x" * 56  # PostgreSQL's 63-byte identifier limit.
    await connection.execute(text(f'CREATE TYPE public."{name}" AS ENUM (\'open\', \'old\')'))
    await connection.execute(text(f'CREATE TABLE public.safety_rows (state public."{name}")'))
    await connection.execute(text("INSERT INTO public.safety_rows VALUES ('old')"))
    await connection.execute(text("CREATE SCHEMA safety_shadow"))
    await connection.execute(text(f'CREATE TYPE safety_shadow."{name}" AS ENUM (\'untouched\')'))
    await connection.execute(text("SET LOCAL search_path TO safety_shadow, public"))
    await prepare_enum_transitions(connection, (transition(name),), registry(name))
    assert await connection.scalar(text("SELECT state::text FROM public.safety_rows")) == "new"
    assert await connection.scalar(text(f"SELECT 'untouched'::safety_shadow.\"{name}\"::text")) == "untouched"


@pytest.mark.asyncio
async def test_shared_enum_reordering_preserves_indexes_nulls_and_defaults(connection):
    await setup(connection)
    await connection.execute(text("CREATE INDEX safety_index ON public.safety_rows(state)"))
    await connection.execute(text("CREATE TABLE public.safety_more (state public.safety_state UNIQUE DEFAULT 'open')"))
    await connection.execute(text("INSERT INTO public.safety_more VALUES ('old'), (NULL)"))
    change = EnumTransition("safety_state", ("open", "old"), ("new", "open"))
    await prepare_enum_transitions(connection, (change,), registry())
    await connection.execute(text("INSERT INTO public.safety_more DEFAULT VALUES"))
    assert (await connection.execute(text("SELECT state::text FROM public.safety_more ORDER BY state"))).scalars().all() == ["new", "open", None]
    assert await connection.scalar(text("SELECT indisvalid FROM pg_index WHERE indexrelid='public.safety_index'::regclass"))


@pytest.mark.asyncio
async def test_many_to_one_mapping_cannot_break_a_unique_key(connection):
    await setup(connection)
    await connection.execute(text("ALTER TABLE public.safety_rows ADD UNIQUE (state)"))
    await connection.execute(text("INSERT INTO public.safety_rows VALUES ('open')"))
    mappings = DbAdminRegistry()
    mappings.register_enum_mapping(DbAdminEnumMapping("safety_state", {"old": "open"}))
    with pytest.raises(DbAdminFatalError, match="dependency"):
        await prepare_enum_transitions(connection, (EnumTransition("safety_state", ("open", "old"), ("open",)),), mappings)
    assert await connection.scalar(text("SELECT count(DISTINCT state) FROM public.safety_rows")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", [RuntimeError, asyncio.CancelledError])
async def test_failed_batch_rolls_back_ddl_defaults_and_rows_then_retries(connection, interruption):
    from sqlalchemy import event

    await setup(connection)
    await connection.execute(text("CREATE TYPE public.safety_second AS ENUM ('open', 'old')"))
    await connection.execute(text("CREATE TABLE public.safety_second_rows (state public.safety_second DEFAULT 'old')"))
    await connection.execute(text("INSERT INTO public.safety_second_rows DEFAULT VALUES"))
    await connection.execute(text("CREATE TYPE public.safety_add AS ENUM ('open')"))
    changes = (EnumTransition("safety_add", ("open",), ("open", "extra")), transition(), transition("safety_second"))
    mappings = registry()
    mappings.register_enum_mapping(DbAdminEnumMapping("safety_second", {"old": "new"}))

    # Simulate cancellation after the first enum has been converted. Exercise
    # real DDL and PostgreSQL rollback, not mocked migration operations.
    def interrupt(conn, cursor, statement, parameters, context, executemany):
        if 'ALTER TABLE "public"."safety_second_rows"' in statement:
            raise interruption("synthetic interruption")

    event.listen(connection.sync_connection, "before_cursor_execute", interrupt)
    try:
        with pytest.raises(interruption, match="synthetic interruption"):
            await prepare_enum_transitions(connection, changes, mappings)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", interrupt)
    assert await connection.scalar(text("SELECT state::text FROM public.safety_rows")) == "old"
    await connection.execute(text("INSERT INTO public.safety_rows DEFAULT VALUES"))
    assert await connection.scalar(text("SELECT count(*) FROM public.safety_rows WHERE state='old'")) == 2
    assert await connection.scalar(text("SELECT count(*) FROM pg_type WHERE typname LIKE 'dbadmin_enum_%' OR typname LIKE 'dbadmin_old_%'")) == 0
    assert await connection.scalar(text("SELECT count(*) FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid WHERE t.typname='safety_add'")) == 1
    await prepare_enum_transitions(connection, changes, mappings)
    assert await connection.scalar(text("SELECT state::text FROM public.safety_second_rows")) == "new"


@pytest.mark.asyncio
@pytest.mark.parametrize("label", [":parameter", "quote'and\\slash", "été"])
async def test_label_conversion_preserves_literals(connection, label):
    await setup(connection)
    change = EnumTransition("safety_state", ("open", "old"), ("open", label))
    mappings = DbAdminRegistry()
    mappings.register_enum_mapping(DbAdminEnumMapping("safety_state", {"old": label}))
    await prepare_enum_transitions(connection, (change,), mappings)
    await connection.execute(text("INSERT INTO public.safety_rows DEFAULT VALUES"))
    assert (await connection.execute(text("SELECT state::text FROM public.safety_rows"))).scalars().all() == [label, label]
    # A later release must recognize and preserve that quoted constant default.
    mappings = DbAdminRegistry()
    mappings.register_enum_mapping(DbAdminEnumMapping("safety_state", {label: "final"}))
    await prepare_enum_transitions(connection, (EnumTransition("safety_state", ("open", label), ("open", "final")),), mappings)
    await connection.execute(text("INSERT INTO public.safety_rows DEFAULT VALUES"))
    assert (await connection.execute(text("SELECT state::text FROM public.safety_rows"))).scalars().all() == ["final"] * 3


@pytest.mark.asyncio
async def test_lock_timeout_leaves_upgrade_replayable():
    from sqlalchemy.exc import DBAPIError

    async with engine.begin() as connection:
        await setup(connection)
    try:
        async with engine.begin() as blocker:
            await blocker.execute(text("LOCK TABLE public.safety_rows IN ACCESS SHARE MODE"))
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL lock_timeout='50ms'"))
                with pytest.raises(DBAPIError, match="lock timeout"):
                    await prepare_enum_transitions(connection, (transition(),), registry())
                assert await connection.scalar(text("SELECT state::text FROM public.safety_rows")) == "old"
        async with engine.begin() as connection:
            await prepare_enum_transitions(connection, (transition(),), registry())
            await connection.execute(text("INSERT INTO public.safety_rows DEFAULT VALUES"))
            assert await connection.scalar(text("SELECT count(*) FROM public.safety_rows WHERE state='new'")) == 2
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE public.safety_rows"))
            await connection.execute(text("DROP TYPE public.safety_state"))
        await engine.dispose()
