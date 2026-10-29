"""Live, source-authorized folder collections; all fixtures are synthetic."""

from uuid import uuid4
import json

import pytest

from app.agent import AgentManagementScope
from app.document import document_tags, document_nesting
from app.document.schemas import DocumentTagWrite
from app.document.tests.test_sharing_inheritance import human, document, rule
from app.file_share import ResourceContext, parse_resource_uri, resource_info, resource_list, resource_read, resource_search
from core.user import HumanActor


def test_folder_reference_is_a_stable_collection():
    identity = uuid4()
    assert str(parse_resource_uri(f"document://folders/{identity}")) == f"document://folders/{identity}/"
    assert parse_resource_uri(f"document://folders/{identity}/").is_collection
    assert str(parse_resource_uri("document://folders/")) == "document://folders/"
    for uri in ("document://folders/not-an-id/", f"document://folders/{identity}/extra"):
        with pytest.raises(ValueError):
            parse_resource_uri(uri)


@pytest.mark.asyncio
async def test_folder_scope_membership_is_live_and_does_not_authorize_other_effects(db, agents, memory_storage):
    from app.agent import EffectDescriptorV1, admitted_scope, collection_scope_targets, preflight
    owner = await human(db)
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic scope root", parent_id=None))
    child = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic scope child", parent_id=root.id))
    first = await document(agents[0], owner, "Synthetic scoped document")
    nested = await document(agents[0], owner, "Synthetic scoped nested document")
    await document_tags.move_document(scope, first.id, child.id)
    await document_nesting.move(scope, nested.id, first.id)
    await rule(root, scope, [("agent", agents[1].id, False)])
    uri = f"document://folders/{root.id}/"
    admitted = admitted_scope(uuid4(), f'<p>Prefix obsolete titles within <a href="{uri}">this folder</a>; delete nothing.</p>')

    async def decision(target, kind="mutate", capability="file.write"):
        effect = EffectDescriptorV1(capability=capability, kind=kind, target_arguments=("uri",))
        arguments = {"uri": target}
        members = await collection_scope_targets(admitted, effect, arguments, agents[1].id)
        return preflight(admitted, effect, "synthetic", arguments, produced_targets=members).decision

    assert await decision(f"document://{first.id}") == "allow"
    assert await decision(f"document://{nested.id}") == "allow"
    assert await decision(f"document://{uuid4()}") == "clarify"
    assert await decision(f"document://{first.id}/attachments/") == "clarify"
    assert await decision(f"document://{first.id}", "delete", "file.delete") == "clarify"
    assert await decision(f"document://{first.id}", "transport", "file.copy") == "clarify"
    await document_nesting.move(scope, nested.id, None)
    assert await decision(f"document://{nested.id}") == "clarify"
    await rule(root, scope)
    assert await decision(f"document://{first.id}") == "clarify"


@pytest.mark.asyncio
async def test_folder_discovery_contents_and_revocation(db, agents, memory_storage):
    from app.document.folder_resources import describe_folder, list_folder

    owner, outsider = await human(db), await human(db)
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic collection", parent_id=None, icon="folder:blue"))
    child = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic subcollection", parent_id=root.id))
    private = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic private sibling", parent_id=None))
    first = await document(agents[0], owner, "Synthetic first document")
    nested = await document(agents[0], owner, "Synthetic nested document")
    await document_tags.move_document(scope, first.id, child.id)
    await document_nesting.move(scope, nested.id, first.id)
    uri = f"document://folders/{root.id}/"
    ctx = ResourceContext(agent_id=agents[1].id, runtime="internal")
    with pytest.raises((PermissionError, FileNotFoundError)):
        await resource_info(ctx, uri)
    await rule(root, scope, [("agent", agents[1].id, False)])
    info = await resource_info(ctx, uri)
    assert info.is_collection and info.metadata["icon"] == "folder:blue"
    assert {"info", "list", "read"} <= set(info.capabilities)
    discovered = await resource_list(ctx, "document://folders/", max_entries=500)
    assert {entry.uri for entry in discovered.entries} == {uri, f"document://folders/{child.id}/"}
    assert f"document://folders/{private.id}/" not in {entry.uri for entry in discovered.entries}
    root_entries = await resource_list(ctx, "document://", max_entries=1)
    assert root_entries.entries[0].uri == "document://folders/"
    assert root_entries.next_cursor is not None
    entries = []
    cursor = None
    while True:
        page = await resource_list(ctx, uri, max_entries=1, cursor=cursor)
        entries.extend(page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(entries) == len({entry.uri for entry in entries}) == 3
    assert {f"document://{first.id}", f"document://{nested.id}"} <= {entry.uri for entry in entries}
    found = await resource_search(ctx, uri, "nested")
    assert [hit.resource.uri for hit in found.hits] == [f"document://{nested.id}"]
    read = await resource_read(ctx, uri)
    tree = json.loads(read.content)
    assert read.media_type == "application/json" and read.next_offset is None
    assert tree["uri"] == uri
    subfolder = tree["children"][0]
    assert subfolder["uri"] == f"document://folders/{child.id}/"
    parent_document = subfolder["children"][0]
    assert parent_document["uri"] == f"document://{first.id}"
    assert parent_document["children"][0]["uri"] == f"document://{nested.id}"
    assert "Synthetic content" in (await resource_read(ctx, parent_document["uri"])).content
    assert tree["pagination"]["total"] == 3
    assert tree["continuations"] == []
    second = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic second location", parent_id=root.id))
    await document_tags.assign_tag(scope, first.id, second.id)
    repeated = json.loads((await resource_read(ctx, uri)).content)
    placements = [entry["children"][0] for entry in repeated["children"]]
    assert [entry["uri"] for entry in placements] == [f"document://{first.id}"] * 2
    assert placements[0]["key"] != placements[1]["key"]
    assert all(entry["children"][0]["uri"] == f"document://{nested.id}" for entry in placements)
    # Damaged legacy placement must not turn a read into an unbounded traversal.
    from app.document import DocumentNesting
    from sqlalchemy import text
    cycle = DocumentNesting(user_id=owner.id, document_id=first.id, parent_document_id=nested.id)
    db.add(cycle)
    await db.flush()
    await db.execute(text("SET LOCAL statement_timeout = '5s'"))
    cyclic = json.loads((await resource_read(ctx, uri)).content)
    assert cyclic["pagination"]["total"] == 6
    await db.execute(text("SET LOCAL statement_timeout = DEFAULT"))
    await db.delete(cycle)
    await db.flush()
    from app.messenger.link_preview import preview_reference
    preview = await preview_reference(uri, agent_id=agents[1].id)
    assert preview is not None and preview.kind == "resource"
    assert preview.metadata["icon"] == "folder:blue"
    assert not preview.download_available
    with pytest.raises(FileNotFoundError):
        await describe_folder(root.id, HumanActor(outsider.id))
    assert (await describe_folder(root.id, HumanActor(owner.id)))["name"] == root.name
    await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic renamed collection", parent_id=None), root.id)
    assert (await resource_info(ctx, uri)).name == "Synthetic renamed collection"
    await rule(root, scope)
    with pytest.raises(FileNotFoundError):
        await list_folder(root.id, agents[1].id, limit=50, offset=0)
    with pytest.raises(FileNotFoundError):
        await resource_read(ctx, uri)
    assert not (await resource_list(ctx, "document://folders/")).entries
    # Sharing a child never exposes its private ancestors or siblings.
    await rule(child, scope, [("agent", agents[1].id, False), ("user", outsider.id, False)])
    assert [entry.uri for entry in (await resource_list(ctx, "document://folders/")).entries] == [f"document://folders/{child.id}/"]
    assert (await describe_folder(child.id, HumanActor(outsider.id)))["name"] == child.name
    with pytest.raises(FileNotFoundError):
        await describe_folder(root.id, HumanActor(outsider.id))
    await document_tags.remove_tag(owner.id, child.id, confirmed=True)
    with pytest.raises(FileNotFoundError):
        await resource_info(ctx, f"document://folders/{child.id}/")


@pytest.mark.asyncio
async def test_folder_http_authorization_and_independent_attachment_membership(client):
    path = "/api/documents/folder-collections"
    assert (await client.get(path)).status_code == 401
    credentials = {"email": "synthetic-folder-owner@example.com", "password": "Synthetic-folder-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    created = await client.post("/api/documents/tags", headers=headers, json={"name": "Synthetic collection", "parent_id": None})
    assert created.status_code == 200, created.text
    folder = created.json()
    uri = f"document://folders/{folder['id']}/"
    page = await client.get(path, headers=headers)
    assert page.status_code == 200, page.text
    assert uri in {entry["uri"] for entry in page.json()["entries"]}
    assert (await client.get(path + "/" + str(uuid4()), headers=headers)).status_code == 404
    assert (await client.get(path, headers=headers, params={"agent_id": 2147483647})).status_code in {403, 404}
    assert (await client.get(path, headers=headers, params={"limit": 500})).status_code == 200
    # Linking an authorized collection creates no grants and no binary copy.
    agents = (await client.get("/api/agents/selection", headers=headers)).json()
    agent = agents[0]["id"]
    doc = await client.post("/api/documents", headers=headers, json={"title": "Synthetic carrier", "owner_kind": "agent", "owner_id": agent, "actor_agent_id": agent, "document_type": "html", "folder": ""})
    assert doc.status_code == 201, doc.text
    identity = doc.json()["id"]
    attached = await client.put(f"/api/documents/{identity}/internal-attachments", headers=headers, params={"actor_agent_id": agent},
        json={"uris": [uri], "resource_agent_id": agent, "expected_lock_version": doc.json()["lock_version"]})
    assert attached.status_code == 200, attached.text
    assert attached.json()["items"][0]["uri"] == uri
    info = await client.get(path + "/" + folder["id"], headers=headers, params={"agent_id": agent})
    assert info.status_code == 404


@pytest.mark.asyncio
async def test_folder_membership_does_not_grant_foreign_documents(db, agents, memory_storage):
    from app.document.folder_resources import list_folder

    owner, other = await human(db), await human(db)
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    folder = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic collection", parent_id=None))
    from app.document import document_sharing
    from app.document.schemas import DocumentSharingUpdate
    foreign = await document(agents[0], other, "Synthetic foreign document")
    other_scope = AgentManagementScope(user_id=other.id, agent_ids=frozenset())
    await document_sharing.update_sharing(foreign.id, DocumentSharingUpdate(kind="user", id=owner.id,
        can_write=False, expected_lock_version=foreign.lock_version), other_scope)
    await document_tags.assign_tag(scope, foreign.id, folder.id)
    await rule(folder, scope, [("agent", agents[1].id, False)])
    page = await list_folder(folder.id, agents[1].id, limit=50, offset=0)
    assert page["entries"] == []
    tree = json.loads((await resource_read(ResourceContext(agent_id=agents[1].id, runtime="internal"),
        f"document://folders/{folder.id}/")).content)
    assert tree["children"] == []
    assert str(foreign.id) not in json.dumps(tree)
    # Readable descendants remain discoverable without disclosing their denied parent.
    visible_child = await document(agents[1], owner, "Synthetic independently readable child")
    await document_nesting.move(scope, visible_child.id, foreign.id)
    tree = json.loads((await resource_read(ResourceContext(agent_id=agents[1].id, runtime="internal"),
        f"document://folders/{folder.id}/")).content)
    assert tree["children"][0]["uri"] == f"document://{visible_child.id}"
    assert tree["children"][0]["parent_uri"] == tree["uri"]
    assert str(foreign.id) not in json.dumps(tree)


@pytest.mark.asyncio
@pytest.mark.parametrize("item_count", [200, 201, 405])
async def test_folder_tree_pages_are_complete_json_and_preserve_parentage(db, agents, memory_storage, monkeypatch, item_count):
    from hashlib import sha256
    from unittest.mock import AsyncMock
    from app.document import Document, DocumentTagAssignment
    from app.file_share import mcp
    from app.tools import McpToolContext
    from core.storage import get_storage
    from tests.sharing_fixtures import bind_private_shares

    owner = await human(db)
    scope = AgentManagementScope(user_id=owner.id, agent_ids=frozenset())
    root = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic paged root", parent_id=None))
    branch = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic branch", parent_id=root.id))
    leaf = await document_tags.write_tag(owner.id, DocumentTagWrite(name="Synthetic leaf folder", parent_id=branch.id))
    await rule(root, scope, [("agent", agents[1].id, False)])
    resource = await get_storage("native").create(b"<p>Synthetic paged tree document</p>")
    rows = [{"id": uuid4(), "owner_agent_id": agents[1].id, "resource_id": resource,
        "provider_code": "native", "title": f"Synthetic tree document {index:04d}",
        "content_hash": sha256(b"synthetic").hexdigest()} for index in range(item_count - 2)]
    await bind_private_shares(db, rows, kind="document")
    await db.execute(Document.__table__.insert(), rows)
    await db.execute(DocumentTagAssignment.__table__.insert(), [dict(tag_id=leaf.id,
        document_id=row["id"], position=index) for index, row in enumerate(rows)])
    await db.flush()
    uri = f"document://folders/{root.id}/"
    ctx = ResourceContext(agent_id=agents[1].id, runtime="internal")
    monkeypatch.setattr(mcp, "_resource_context", AsyncMock(return_value=ctx))
    tool_ctx = McpToolContext(agent_id=agents[1].id, runtime="internal")
    seen = {}
    offset = 0
    parents = set()
    pages = 0
    while True:
        # MCP must preserve an entire JSON page even with a small text budget.
        result = json.loads(await mcp.read_file(tool_ctx, uri, offset=offset, max_chars=1))
        assert result["media_type"] == "application/json"
        assert result["offset_unit"] == "item" and result["page_size"] == 200
        tree = json.loads(result["content"])
        if pages == 0:
            assert tree["continuations"] == []
            assert tree["children"][0]["uri"] == f"document://folders/{branch.id}/"
            assert tree["children"][0]["children"][0]["uri"] == f"document://folders/{leaf.id}/"
            parents.add(tree["key"])
        stack = list(tree["children"])
        for continuation in tree["continuations"]:
            assert continuation["parent_key"] in seen
            stack.extend(continuation["children"])
        current = []
        while stack:
            node = stack.pop()
            current.append(node)
            stack.extend(node["children"])
        assert len(current) == min(200, item_count - offset)
        assert tree["pagination"]["total"] == result["total"] == item_count
        assert tree["pagination"]["returned"] == len(current)
        assert result["start"] == offset and result["end"] == offset + len(current)
        for node in current:
            assert node["key"] not in seen
            seen[node["key"]] = node
            parents.add(node["parent_key"])
        pages += 1
        next_offset = result.get("next_offset")
        assert tree["pagination"]["next_offset"] == next_offset
        if next_offset is None:
            break
        assert next_offset == offset + 200
        offset = next_offset
    assert len(seen) == item_count
    assert parents <= {tree["key"], *seen}
    assert {node["uri"] for node in seen.values() if node["kind"] == "document"} == {f"document://{row['id']}" for row in rows}
    beyond = await resource_read(ctx, uri, offset=item_count + 1)
    assert beyond.start == beyond.end == item_count and beyond.next_offset is None
    with pytest.raises(ValueError):
        await resource_read(ctx, uri, offset=-1)
