"""The combined catalogue pages before materialization and preserves both ACL policies."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.agent import AgentManagementScope
from app.process import catalogue, native_definitions, process_service
from app.process.models import ProcessDefinition, ProcessNodeAttempt, ProcessNodeRun, ProcessRun
from app.process.schemas import ProcessDefinitionRead
from app.tools import ToolModel
from app.share import set_grant
from core.user import UserModel
from tests.sql_reads import measured_reads
from .test_native_bpmn import native as native, graph


@pytest.mark.asyncio
async def test_catalogue_shares_native_run_rights_but_isolates_external_launchers(db, native):
    owner, outsider = native
    user = UserModel(email=f"catalogue-{uuid4()}@example.test", hashed_password="synthetic", is_active=True)
    db.add(user)
    await db.flush()
    owner.user_id = user.id
    visible = await native_definitions.create(actor_agent_id=owner.id, title="Visible native", graph=graph(),
        description="Searchable native description")
    hidden = await native_definitions.create(actor_agent_id=outsider.id, title="Private native", graph=graph())
    external = ProcessDefinition(agent_id=owner.id, tool_id=visible.tool_id, engine_process_id=uuid4().hex,
        label="Visible external")
    private_external = ProcessDefinition(agent_id=outsider.id, tool_id=visible.tool_id,
        engine_process_id=uuid4().hex, label="Private external")
    db.add_all([external, private_external])
    await db.flush()
    now = datetime.now(timezone.utc)
    def run(definition, launcher, status, minute):
        record = ProcessRun(process_id=definition.id, launcher_agent_id=launcher.id,
            engine_code="galaris" if definition.code else "synthetic", correlation_id=uuid4().hex,
            callback_token="synthetic", status=status, created_at=now + timedelta(minutes=minute),
            input={"private": "Synthetic payload excluded from summaries"})
        db.add(record)
        return record
    waiting = run(visible, outsider, "waiting", 1)
    completed = run(visible, owner, "success", 0)
    run(hidden, outsider, "running", 2)
    external_visible = run(external, owner, "error", 0)
    run(external, outsider, "running", 3)
    await db.flush()
    node = ProcessNodeRun(run_id=waiting.id, node_key="human", occurrence="human", status="waiting", context={})
    db.add(node)
    await db.flush()
    db.add(ProcessNodeAttempt(node_run_id=node.id, number=1, status="human_waiting"))
    await db.flush()
    scope = AgentManagementScope(user.id, frozenset({owner.id}))
    result = await catalogue.page_for(scope)
    assert result.total == 2
    items = {item.id: item for item in result.items}
    assert items[visible.id].description == "Searchable native description"
    assert items[visible.id].active_runs == 1 and items[visible.id].human_waiting_runs == 1
    assert items[visible.id].latest_run.id == waiting.id
    assert items[external.id].active_runs == 0 and items[external.id].latest_run.id == external_visible.id
    assert "private" not in result.model_dump_json() and "bpmn_xml" not in result.model_dump_json()
    await set_grant(hidden.share_id, "user", user.id, False)
    shared = await catalogue.page_for(scope)
    assert shared.total == 3 and next(item for item in shared.items if item.id == hidden.id).active_runs == 1
    await set_grant(hidden.share_id, "user", user.id, None)
    assert (await catalogue.page_for(scope)).total == 2
    # Only the latest attempt counts; an old human request must not survive resumption.
    db.add(ProcessNodeAttempt(node_run_id=node.id, number=2, status="started"))
    await db.flush()
    assert (await catalogue.page_for(scope, kind="native")).items[0].human_waiting_runs == 0
    node.context = {"activity_question": {"status": "pending"}}
    await db.flush()
    assert (await catalogue.page_for(scope, kind="native")).items[0].human_waiting_runs == 1
    waiting.status = "success"
    await db.flush()
    assert (await catalogue.page_for(scope, kind="native")).items[0].human_waiting_runs == 0
    visible.archived = True
    await db.flush()
    assert (await catalogue.page_for(scope)).total == 1
    archived = await catalogue.page_for(scope, archive="archived", search="searchable")
    assert [item.id for item in archived.items] == [visible.id]
    assert (await catalogue.page_for(scope, archive="all", kind="external")).total == 1
    external_visible.deleted_at = now
    await db.flush()
    assert (await catalogue.page_for(scope, kind="external")).items[0].latest_run is None
    assert completed.id != waiting.id


@pytest.mark.asyncio
async def test_catalogue_paginates_beyond_500_without_loading_all_definitions(db, native):
    owner, _ = native
    user = UserModel(email=f"catalogue-page-{uuid4()}@example.test", hashed_password="synthetic", is_active=True)
    tool = ToolModel(code=f"catalogue-{uuid4().hex}", label="Synthetic engine", connection_schema={})
    db.add_all([user, tool])
    await db.flush()
    owner.user_id = user.id
    db.add_all([ProcessDefinition(agent_id=owner.id, tool_id=tool.id, engine_process_id=f"synthetic-{index}",
        label=f"Synthetic {index:04}", description="Synthetic description " * 50) for index in range(505)])
    await db.flush()
    scope = AgentManagementScope(user.id, frozenset({owner.id}))
    old = await process_service.list_definitions(agent_ids=scope.agent_ids)
    old_bytes = len(json.dumps([ProcessDefinitionRead.model_validate(item).model_dump(mode="json") for item in old]).encode())
    async with measured_reads(db, "catalogue-page-50") as reads:
        first = await catalogue.page_for(scope)
    assert len(first.items) == 50 and first.total == 505
    # Bounded query count regardless of page size, including grouped run summaries.
    assert len(reads) <= 4
    async with measured_reads(db, "catalogue-page-500") as larger_reads:
        large = await catalogue.page_for(scope, page=2, page_size=500)
    assert len(larger_reads) <= 4
    assert large.total == 505 and len(large.items) == 5 and large.items[-1].label == "Synthetic 0504"
    new_bytes = len(first.model_dump_json().encode())
    assert new_bytes < old_bytes
    print(f"CATALOGUE_TRANSFER old_items={len(old)} old_bytes={old_bytes} page_items=50 page_bytes={new_bytes}")
    assert (await catalogue.page_for(scope, search="description", kind="external")).total == 505
    assert (await catalogue.page_for(scope, search="%_")).total == 0
    assert (await catalogue.page_for(scope, page=500, page_size=50)).page == 11
