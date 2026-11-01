"""Atlas upgrades batched legacy Process ACLs without changing sources.

Historical Document/Memory separation and its ACLs are exercised through the
real Atlas pipeline in app/document/tests/test_independence_upgrade.py. Dataset
conversion and populated FK redirection are covered in test_typed_document_upgrade;
its legacy ACL transfer matrix is covered in this package's test_sharing. Memory
is private in the target schema and no longer has a share owner or grant ORM.
"""

from dataclasses import replace

import pytest
from sqlalchemy import select, text

from app.agent import Agent
from app.agent.models import Title
from app.process.models import ProcessDefinition, ProcessDefinitionGrant
from app.share.dbadmin import register_dbadmin
from app.share.migration import complete
from app.tools import ToolModel
from core import settings
from core.dbadmin import DbAdminRegistry, DbAdminVerdict, orchestrator
from core.dbadmin._internal import atlas
from core.team import TeamModel
from core.user import UserModel


async def sources(session):
    return {
        table: list(
            (
                await session.execute(
                    text(
                        f"SELECT to_jsonb(r) - 'share_id' - 'share_kind' FROM {table} r ORDER BY id"
                    )
                )
            ).scalars()
        )
        for table in (
            "process_definitions",
            "process_definition_grants",
        )
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_populated_legacy_upgrade_keeps_exact_rights_sources_and_restarts_after_committed_ddl(
    committed_database,
    monkeypatch,
    interrupted,
):
    isolated_engine = committed_database.kw["bind"]
    monkeypatch.setattr(orchestrator, "engine", isolated_engine)
    monkeypatch.setattr(atlas, "engine", isolated_engine)
    monkeypatch.setattr(settings, "POSTGRES_DB", isolated_engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    expected = {}
    async with committed_database() as db:
        manager = UserModel(
            email="synthetic-upgrade-owner@example.test",
            hashed_password="unused",
            is_active=True,
        )
        recipient = UserModel(
            email="synthetic-upgrade-reader@example.test",
            hashed_password="unused",
            is_active=True,
        )
        title = Title(label="Synthetic historical sharing", gender="X")
        owner = Agent(
            user=manager,
            title=title,
            code="synthetic-upgrade-owner",
            first_name="Synthetic",
            last_name="Owner",
            agent_driver="internal",
        )
        peer = Agent(
            user=recipient,
            title=title,
            code="synthetic-upgrade-reader",
            first_name="Synthetic",
            last_name="Reader",
            agent_driver="internal",
        )
        team = TeamModel(name="Synthetic historical recipients")
        db.add_all([owner, peer, team])
        await db.flush()
        tool = await db.scalar(select(ToolModel.id).where(ToolModel.code == "galaris"))
        for index in range(121):
            public = index % 3
            groups = (index // 3) % 3 if public == 0 else 0
            row = ProcessDefinition(
                agent_id=owner.id,
                tool_id=tool,
                label=f"Synthetic legacy workflow {index}",
                engine_process_id=f"legacy_{index}",
                code=f"legacy_{index}",
                bpmn_xml="<synthetic/>",
            )
            db.add(row)
            await db.flush()
            if index % 5 == 0:
                row.soft_delete()
            grants = set()
            for principal, identity, write in (
                ("agent", peer.id, bool(index % 2)),
                ("user", recipient.id, not bool(index % 2)),
                ("team", team.id, bool(index % 3)),
            ):
                grant = ProcessDefinitionGrant(
                    can_write=write,
                    **{"process_id": row.id, principal + "_id": identity},
                )
                db.add(grant)
                grants.add((principal, identity, write))
            await db.flush()
            await db.execute(
                text("UPDATE process_definitions SET global_access = :public, group_access = :groups WHERE id = :id"),
                {"id": row.id, "public": public, "groups": groups},
            )
            expected[("process_definitions", str(row.id))] = (public, groups, grants)
        await db.commit()
        before = await sources(db)
        for table in ("documents", "document_tags", "datasets", "process_definitions"):
            await db.execute(
                text(
                    f"ALTER TABLE {table} DROP COLUMN share_id CASCADE, DROP COLUMN share_kind CASCADE"
                )
            )
        await db.execute(text("ALTER TABLE document_sharing_intents DROP CONSTRAINT document_sharing_intents_share_id_fkey"))
        await db.execute(text("DROP TABLE share_grants, share_configs"))
        await db.commit()
    registry = DbAdminRegistry()
    register_dbadmin(registry)
    if interrupted:
        action = registry.actions[0]

        async def fail_after_copy(session, delta):
            await action.handler(session, delta)
            raise RuntimeError(
                "Synthetic interruption before sharing transaction commit"
            )

        failing = DbAdminRegistry()
        failing.register_action(replace(action, handler=fail_after_copy))
        result = await orchestrator.synchronize_database(target_registry=failing)
        assert result.verdict is DbAdminVerdict.FATAL
        async with committed_database() as db:
            assert await db.scalar(text("SELECT count(*) FROM share_configs")) == 0
            assert (
                await db.scalar(
                    text("SELECT count(*) FROM process_definitions WHERE share_id IS NULL")
                )
                == 121
            )
            assert await sources(db) == before
    result = await orchestrator.synchronize_database(target_registry=registry)
    assert result.verdict is DbAdminVerdict.CONVERGED
    async with committed_database() as db:
        assert await complete(db)
        assert await sources(db) == before
        for (table, identity), (public, groups, grants) in expected.items():
            policy = (
                await db.execute(
                    text(f"""SELECT s.id, s.global_access, s.group_access FROM {table} r
                JOIN share_configs s ON s.id = r.share_id WHERE r.id::text = :id"""),
                    {"id": identity},
                )
            ).one()
            assert (policy.global_access, policy.group_access) == (public, groups)
            actual = set()
            for grant in (
                await db.execute(
                    text(
                        "SELECT agent_id,user_id,team_id,can_write FROM share_grants WHERE share_id = :id"
                    ),
                    {"id": policy.id},
                )
            ).mappings():
                principal = next(
                    kind
                    for kind in ("agent", "user", "team")
                    if grant[kind + "_id"] is not None
                )
                actual.add((principal, grant[principal + "_id"], grant["can_write"]))
            assert actual == grants
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('memory_items','documents','datasets','process_definitions') AND column_name IN ('share_id','share_kind') AND is_nullable='YES'"
                )
            )
            == 0
        )
        assert await db.scalar(text("SELECT count(*) FROM share_configs")) == 121
    replay = await orchestrator.synchronize_database(target_registry=registry)
    assert replay.verdict is DbAdminVerdict.CONVERGED
    async with committed_database() as db:
        assert await sources(db) == before
        assert await db.scalar(text("SELECT count(*) FROM share_configs")) == 121
