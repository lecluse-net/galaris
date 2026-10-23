"""Personal ordering must not transfer the contents of the visible library."""

import gc
import hashlib
import json
from pathlib import Path
import time
import tracemalloc
from uuid import uuid4

import pytest
from sqlalchemy import event, select, update

from app.agent import AgentManagementScope
from app.document import document_order
from app.memory.models import MemoryLink
from app.document import Document, DocumentListPosition, DocumentTag
from app.document.schemas import DocumentOrderMove, DocumentOrderNode
from core.storage import get_storage
from core.user import UserModel
from tests.sharing_fixtures import bind_private_shares


@pytest.mark.asyncio
@pytest.mark.parametrize("list_only", [True, False])
async def test_personal_order_memory_does_not_grow_with_sibling_contents(db, agents, memory_storage, list_only):
    user = UserModel(email="ordering-performance@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    user_id = user.id
    owner_id = agents[0].id
    scope = AgentManagementScope(user_id=user_id, agent_ids=frozenset({owner_id}))
    resource = await get_storage("native").create(b"synthetic ordering benchmark")
    rows = [{
        "id": uuid4(), "owner_agent_id": owner_id, "resource_id": resource, "provider_code": "native",
        "title": f"Synthetic ordering document {index:04d}",
        "content_hash": hashlib.sha256(str(index).encode()).hexdigest(),
    } for index in range(120)]
    await bind_private_shares(db, rows, kind="document")
    await db.execute(Document.__table__.insert(), rows)
    request = DocumentOrderMove(
        node=DocumentOrderNode(kind="document", id=rows[-1]["id"]), list_only=list_only,
        anchor=DocumentOrderNode(kind="document", id=rows[0]["id"]), after=False,
    )
    measurements = []
    for content_bytes in (0, 64 * 1024):
        # Both the summary and the separate document may carry inline payloads.
        payload = "x" * content_bytes
        await db.execute(update(Document).where(Document.id.in_([row["id"] for row in rows])).values(summary_content=payload))
        await db.execute(update(Document).where(Document.id.in_([row["id"] for row in rows])).values(content=payload))
        await db.commit()
        db.expunge_all()
        gc.collect()
        tracemalloc.start()
        started = time.perf_counter()
        try:
            await document_order.reorder(scope, request)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            elapsed = time.perf_counter() - started
            tracemalloc.stop()
        measurements.append({"content_bytes": content_bytes, "python_peak_bytes": peak, "seconds": elapsed})
        ordered = list(await db.scalars(select(DocumentListPosition.document_id).where(
            DocumentListPosition.user_id == user_id,
        ).order_by(DocumentListPosition.position)))
        assert ordered == [rows[-1]["id"], *[row["id"] for row in rows[:-1]]]

    destination = Path(__file__).resolve().parents[4] / f"artifacts/document-order-benchmark-{list_only}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    # A single moved document may be read for authorization/projection. Its peers'
    # payloads must not add megabytes to an operation that changes only positions.
    assert measurements[1]["python_peak_bytes"] <= measurements[0]["python_peak_bytes"] + 2 * 1024 * 1024, measurements


@pytest.mark.asyncio
async def test_folder_position_change_does_not_rebuild_the_structural_tree(db, agents, memory_storage):
    from app.memory.document_structure import sync_folder_structure

    user = UserModel(email="folder-order-performance@example.test", hashed_password="unused", is_active=True)
    db.add(user)
    await db.flush()
    user_id = user.id
    scope = AgentManagementScope(user_id=user_id, agent_ids=frozenset({agents[0].id}))
    root = DocumentTag(user_id=user_id, name="Synthetic root")
    db.add(root)
    await db.flush()
    children = [DocumentTag(user_id=user_id, parent_id=root.id, name=f"Synthetic folder {index:03d}", position=index + 1)
                for index in range(30)]
    db.add_all(children)
    await db.flush()
    await sync_folder_structure(user_id)
    identities = [child.id for child in children]
    root_id = root.id
    links = set(await db.scalars(select(MemoryLink.id).where(MemoryLink.relation_type == "parent_of")))
    assert len(links) == len(children)
    await db.commit()
    db.expunge_all()
    statements = []
    connection = await db.connection()

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    started = time.perf_counter()
    try:
        await document_order.reorder(scope, DocumentOrderMove(
            node=DocumentOrderNode(kind="tag", id=identities[-1]), parent_id=root_id,
            anchor=DocumentOrderNode(kind="tag", id=identities[0]), after=False,
        ))
    finally:
        elapsed = time.perf_counter() - started
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    measurements = {"folders": 31, "statements": len(statements), "seconds": elapsed}
    destination = Path(__file__).resolve().parents[4] / "artifacts/folder-order-benchmark.json"
    destination.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    ordered = list(await db.scalars(select(DocumentTag.id).where(DocumentTag.parent_id == root_id).order_by(DocumentTag.position)))
    assert ordered == [identities[-1], *identities[:-1]]
    assert set(await db.scalars(select(MemoryLink.id).where(MemoryLink.relation_type == "parent_of"))) == links
    assert len(statements) < 15, measurements
