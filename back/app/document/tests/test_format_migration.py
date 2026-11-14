"""A populated column/contract rename preserves content, history, policy and runs."""

from dataclasses import replace
from hashlib import sha256
import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.agent.models import Agent, Title
from app.document.models import Document, DocumentRevision
from app.document.data.models import Dataset
from app.document.format_migration import register as register_document
from app.process.document_format_migration import register as register_process, rename_bpmn, rename_graph
from app.process.models import ProcessDefinition, ProcessDefinitionRevision, ProcessRun
from app.share import ShareGrant
from core import settings as settings_module
from core.database import get_db_session
from core.dbadmin import DbAdminRegistry, DbAdminVerdict, orchestrator
from core.dbadmin._internal import atlas
from core.user import UserModel


def old_workflow():
    variables = [{"name": "report", "type": "Document", "nullable": True, "document_type": "data"},
        {"name": "payload", "type": "object", "nullable": True,
         "default": {"type": "object", "value": {"document_type": "user-owned"}}}]
    graph = {"schema_version": "galaris.bpmn/v2", "variables": variables, "nodes": []}
    settings = json.dumps({key: value for key, value in graph.items() if key != "nodes"})
    xml = ('<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:g="https://galaris.ai/bpmn/v1"><!-- preserve layout and comments -->'
        '<bpmn:process id="synthetic"><bpmn:extensionElements><g:workflow label="x > y"><![CDATA['
        + settings + ']]></g:workflow></bpmn:extensionElements></bpmn:process></bpmn:definitions>')
    return graph, xml


def test_only_format_constraints_change_in_bpmn_and_frozen_graphs():
    graph, xml = old_workflow()
    migrated = rename_graph(graph)
    assert migrated["variables"][0]["document_format"] == "data"
    assert "document_type" not in migrated["variables"][0]
    assert migrated["variables"][1] == graph["variables"][1]
    result = rename_bpmn(xml)
    assert result.startswith(xml.split('<![CDATA[')[0])
    assert result.endswith(xml.split(']]>')[1])
    assert '"document_format": "data"' in result
    assert '"document_type": "user-owned"' in result
    assert rename_bpmn(result) == result and rename_graph(migrated) == migrated
    broken = {"variables": [{"document_type": "text", "document_format": "data"}]}
    with pytest.raises(ValueError, match="Conflicting"):
        rename_graph(broken)
    assert broken["variables"][0]["document_type"] == "text"


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_dbadmin_renames_populated_documents_and_process_contracts_without_aliases(
    committed_database, monkeypatch, interrupted,
):
    engine = committed_database.kw["bind"]
    monkeypatch.setattr(atlas, "engine", engine)
    monkeypatch.setattr(orchestrator, "engine", engine)
    monkeypatch.setattr(settings_module, "POSTGRES_DB", engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    graph, xml = old_workflow()
    identities = {}
    async with get_db_session() as session:
        owner = UserModel(email="synthetic-format-migration@example.test", hashed_password="unused", is_active=True)
        title = Title(label="Synthetic format migration", gender="X")
        agent = Agent(user=owner, title=title, code="synthetic-format-migration", first_name="Synthetic", last_name="Owner", agent_driver="internal")
        session.add(agent)
        await session.flush()
        for code in ("text", "data", "html", "form", "example.custom"):
            body = '{"document_type":"preserved user data"}' if code == "data" else "<p>Synthetic preserved bytes.</p>\r\n"
            model = Dataset if code == "data" else Document
            item = model(owner_agent_id=agent.id, title="Synthetic " + code, document_format=code,
                provider_code="native", resource_id=str(uuid4()), content=body,
                content_type="text", media_type="application/json" if code == "data" else "text/html",
                content_hash=sha256(body.encode()).hexdigest(), size_bytes=len(body.encode()), revision=1)
            session.add(item)
            await session.flush()
            identities[code] = item.id
            session.add(DocumentRevision(document_id=item.id, revision=1, provider_code="native", resource_id=item.resource_id,
                content=body, content_hash=item.content_hash, content_type="text", media_type=item.media_type, title=item.title))
            session.add(ShareGrant(share_id=item.share_id, user_id=owner.id, can_write=False))
        tool = await session.scalar(text("SELECT id FROM tools WHERE code='galaris'"))
        definition = ProcessDefinition(agent_id=agent.id, tool_id=tool, engine_process_id="synthetic_format_migration",
            code="synthetic_format_migration", label="Synthetic format migration", bpmn_xml=xml)
        session.add(definition)
        await session.flush()
        session.add(ProcessDefinitionRevision(process_id=definition.id, revision=1, bpmn_xml=xml))
        snapshot = {"definition": {"graph": graph, "xml": xml, "revision": 1},
            "input": {"document_type": "user-owned"}, "authorization_permit": "synthetic-unchanged"}
        run = ProcessRun(process_id=definition.id, launcher_agent_id=agent.id, engine_code="galaris", status="success",
            correlation_id=uuid4().hex, callback_token=uuid4().hex, launch_snapshot=snapshot)
        session.add(run)
        await session.flush()
        run_id, definition_id = run.id, definition.id
    async with engine.begin() as connection:
        before = await connection.scalar(text("SELECT jsonb_agg(to_jsonb(d)-'document_format' ORDER BY id) FROM documents d"))
        history = await connection.scalar(text("SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM document_revisions r"))
        grants = await connection.scalar(text("SELECT jsonb_agg(to_jsonb(g) ORDER BY id) FROM share_grants g"))
        await connection.execute(text("ALTER TABLE documents RENAME COLUMN document_format TO document_type"))
    registry = DbAdminRegistry()
    register_document(registry)
    register_process(registry)
    if interrupted:
        failure_registry = DbAdminRegistry()
        async def fail_after_transfer(session, delta):
            from app.process.document_format_migration import transfer
            await transfer(session, delta)
            raise RuntimeError("Synthetic interrupted format transfer")
        for action in registry.actions:
            failure_registry.register_action(replace(action, handler=fail_after_transfer)
                if action.key == "app.process.document_format_constraints" else action)
        result = await orchestrator.synchronize_database(target_registry=failure_registry)
        assert result.verdict is DbAdminVerdict.FATAL
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='documents' AND column_name='document_type')"))
            # The failed action rolls back its modifications, including terminal snapshots.
            assert (await connection.scalar(text("SELECT launch_snapshot FROM process_runs WHERE id=:id"), {"id": run_id})) == snapshot
    for _ in range(2):
        result = await orchestrator.synchronize_database(target_registry=registry)
        assert result.verdict is DbAdminVerdict.CONVERGED
    async with engine.connect() as connection:
        assert not await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='documents' AND column_name='document_type')"))
        formats = dict((await connection.execute(text("SELECT id,document_format FROM documents"))).all())
        assert {code: formats[identity] for code, identity in identities.items()} == {
            "text": "text", "data": "data", "html": "text", "form": "text", "example.custom": "example.custom"}
        assert await connection.scalar(text("SELECT jsonb_agg(to_jsonb(d)-'document_format' ORDER BY id) FROM documents d")) == before
        assert await connection.scalar(text("SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM document_revisions r")) == history
        assert await connection.scalar(text("SELECT jsonb_agg(to_jsonb(g) ORDER BY id) FROM share_grants g")) == grants
        assert await connection.scalar(text("SELECT bpmn_xml FROM process_definitions WHERE id=:id"), {"id": definition_id}) == rename_bpmn(xml)
        migrated = await connection.scalar(text("SELECT launch_snapshot FROM process_runs WHERE id=:id"), {"id": run_id})
        assert migrated["definition"]["graph"] == rename_graph(graph)
        assert migrated["input"] == snapshot["input"] and migrated["authorization_permit"] == snapshot["authorization_permit"]
        assert await connection.scalar(text("SELECT status FROM process_runs WHERE id=:id"), {"id": run_id}) == "success"
