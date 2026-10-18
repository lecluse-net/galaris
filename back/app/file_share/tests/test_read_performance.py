"""File source discovery and progress reads stay bounded on synthetic corpora."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import event, inspect, select

from app.agent.models import Agent, Title
from app.connection.models import Connection, ConnectionParam
from app.file_share import indexing, resource_service
from app.file_share.models import FileIndexRun, FileObservationRepair
from app.file_share.resource_contracts import ResourceContext
from app.tools.models import Tool


def save_report(name, report):
    destination = Path(__file__).resolve().parents[4] / f"artifacts/{name}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")


async def owners(db):
    title = Title(label="Synthetic file reads", gender="M")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"file-read-{index}", first_name="Synthetic", last_name=str(index))
              for index in range(2)]
    db.add_all(agents)
    await db.flush()
    return agents


@pytest.mark.asyncio
async def test_source_discovery_batches_tools_and_observes_configuration_changes(db):
    owner, peer = await owners(db)
    owner_id, peer_id = owner.id, peer.id
    source = Tool(code="synthetic-files", label="Synthetic files",
                  file_share_config={"service": "nextcloud", "base_url": "https://files.example.com"},
                  global_params={"tools.fileindexing": {"value": "known_uris", "forced": True}})
    hidden = Tool(code="synthetic-hidden", label="Synthetic hidden",
                  file_share_config={"service": "nextcloud", "base_url": "https://hidden.example.com"})
    db.add_all([source, hidden])
    await db.flush()
    source_id = source.id
    connection = Connection(tool_id=source.id, agent_id=owner_id, active=True)
    db.add_all([connection, Connection(tool_id=hidden.id, agent_id=peer_id, active=True),
                Connection(tool_id=hidden.id, agent_id=owner_id, active=False)])
    await db.flush()
    db.add(ConnectionParam(connection_id=connection.id, param_name="tools.fileindexing", param_value="recursive"))
    await db.commit()
    reports = []
    for start, stop in ((0, 1), (1, 41)):
        ordinary = [Tool(code=f"synthetic-ordinary-{index}", label=f"Synthetic ordinary {index}")
                    for index in range(start, stop)]
        db.add_all(ordinary)
        await db.flush()
        db.add_all([Connection(tool_id=tool.id, agent_id=owner_id, active=True) for tool in ordinary])
        await db.commit()
        db.expunge_all()
        connection_db = await db.connection()
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        event.listen(connection_db.sync_connection, "before_cursor_execute", capture)
        try:
            schemes = await resource_service.list_schemes(ResourceContext(agent_id=owner_id, runtime="internal"))
        finally:
            event.remove(connection_db.sync_connection, "before_cursor_execute", capture)
        by_scheme = {scheme.scheme: scheme for scheme in schemes}
        assert by_scheme["synthetic-files"].file_indexing_mode == "known_uris"
        assert by_scheme["synthetic-files"].root_listable
        assert "list" in by_scheme["synthetic-files"].capabilities
        assert "synthetic-hidden" not in by_scheme
        assert not any(code.startswith("synthetic-ordinary") for code in by_scheme)
        assert list(by_scheme) == sorted(by_scheme)
        reports.append({"ordinary_tools": stop, "queries": len(statements)})

    source = await db.get(Tool, source_id)
    source.global_params = {"tools.fileindexing": {"value": "known_uris", "forced": False}}
    await db.commit()
    schemes = await resource_service.list_schemes(ResourceContext(agent_id=owner_id, runtime="internal"))
    assert next(scheme for scheme in schemes if scheme.scheme == "synthetic-files").file_indexing_mode == "recursive"
    peer_schemes = await resource_service.list_schemes(ResourceContext(agent_id=peer_id, runtime="internal"))
    assert "synthetic-files" not in {scheme.scheme for scheme in peer_schemes}
    assert "synthetic-hidden" in {scheme.scheme for scheme in peer_schemes}
    save_report("file-source-read-performance", reports)
    assert all(report["queries"] <= 4 for report in reports), reports


@pytest.mark.asyncio
async def test_progress_does_not_load_traversal_frontiers_and_preserves_pages(db):
    owner, peer = await owners(db)
    owner_id, peer_id = owner.id, peer.id
    now = datetime.now(timezone.utc)
    frontier = [{"uri": f"synthetic-files://folder/{index}/" + "synthetic" * 32,
                 "depth": 1, "cursor": None} for index in range(512)]
    runs = [FileIndexRun(agent_id=owner_id, binding_stamp="synthetic", root_uri=f"synthetic-files://root-{index}/",
                         frontier=frontier, status="running", scanned=index, directories=2,
                         started_at=now, updated_at=now - timedelta(seconds=index), next_attempt_at=now)
            for index in range(64)]
    db.add_all([*runs, FileIndexRun(agent_id=peer_id, binding_stamp="synthetic", root_uri="synthetic-files://private/",
                                   frontier=frontier, started_at=now, updated_at=now, next_attempt_at=now)])
    db.add_all([FileObservationRepair(agent_id=owner_id, binding_stamp="synthetic", runtime="internal",
                                      started_at=now, next_attempt_at=now, payload={}, status=status)
                for status in ("pending", "pending", "error", "success")])
    await db.commit()
    ids = [run.id for run in runs]
    db.expunge_all()
    loaded_frontier_bytes = []

    def loaded(_session, instance):
        if isinstance(instance, FileIndexRun) and "frontier" not in inspect(instance).unloaded:
            loaded_frontier_bytes.append(len(json.dumps(instance.frontier).encode()))

    event.listen(db.sync_session, "loaded_as_persistent", loaded)
    try:
        page = await indexing.index_progress(owner_id, 1, 50)
    finally:
        event.remove(db.sync_session, "loaded_as_persistent", loaded)
    assert page.total == 64 and [run.id for run in page.runs] == ids[:50]
    assert [run.scanned for run in page.runs] == list(range(50))
    assert page.pending_repairs == 2 and page.failed_repairs == 1
    assert all("frontier" not in run.model_dump() for run in page.runs)
    second = await indexing.index_progress(owner_id, 2, 50)
    assert [run.id for run in second.runs] == ids[50:]
    assert (await indexing.index_progress(owner_id, 1, 500)).total == 64
    assert (await indexing.index_progress(owner_id, 3, 50)).runs == []
    assert (await indexing.index_progress(peer_id, 1, 50)).total == 1
    # A subsequent worker read still receives the complete durable traversal.
    worker = await db.scalar(select(FileIndexRun).where(FileIndexRun.id == ids[0]))
    assert worker.frontier == frontier
    report = {"runs": len(page.runs), "loaded_frontier_bytes": sum(loaded_frontier_bytes)}
    save_report("file-index-progress-performance", report)
    assert report["loaded_frontier_bytes"] == 0, report
