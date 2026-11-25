"""Mind map interchange and revision-preserving branch editing."""

from io import BytesIO
import json
from urllib.parse import quote
from zipfile import ZipFile

from PIL import Image
import pytest
from fastmcp import Client
from sqlalchemy import select

from app.connection import facade as connections
from app.connection.models import Connection
from app.document import mcp, resource_service
from app.document.file_import import DocumentImportSource, convert_document_import
from app.document.mindmap import INITIAL_CONTENT, MindMap
from app.document.mindmap.commands import AddBranch, MoveBranch, RemoveBranch, apply_commands
from app.document.mindmap.exchange import MEDIA_TYPE, export_source, import_source
from app.file_share import mcp as files
from app.services import McpToolContext, build_galaris_fastmcp, sync_integrated_service_connections
from app.services.contracts import EXECUTION_META_KEY
from app.services.models import Service

from .revision_helpers import revision_clock as revision_clock


FREEPLANE = b"""<?xml version="1.0"?>
<map version="freeplane 1.12.1"><node ID="root" TEXT="Project &amp; notes">
  <node ID="one" TEXT="First" LINK="https://example.test/resource">
    <richcontent TYPE="NOTE"><html><body><p>Line 1</p><p>Line 2</p></body></html></richcontent>
    <node ID="nested"><richcontent TYPE="NODE"><html><body><p>Nested</p></body></html></richcontent></node>
  </node>
  <node ID="two" TEXT="Second"/>
</node></map>"""


def structure(source):
    mindmap = MindMap.model_validate_json(source)
    children = mindmap.children()

    def branch(node):
        return (node.title, node.note, node.link, [branch(child) for child in children.get(node.id, [])])

    return branch(mindmap.root)


@pytest.mark.parametrize("target", ["freeplane", "freemind", "opml", "xmind"])
def test_interchange_preserves_order_notes_links_and_unicode(target):
    source = import_source("test.mm", "application/octet-stream", FREEPLANE.replace(b"Second", "Étape 二".encode()))
    expected = ("Project & notes", "", "", [
        ("First", "Line 1\nLine 2", "https://example.test/resource", [("Nested", "", "", [])]),
        ("Étape 二", "", "", []),
    ])
    assert structure(source) == expected
    output, mime, suffix = export_source(source, target)
    assert structure(import_source("test" + suffix, mime, output)) == expected
    if target == "xmind":
        with ZipFile(BytesIO(output)) as archive:
            [sheet] = json.loads(archive.read("content.json"))
            assert sheet["rootTopic"]["children"]["attached"][0]["notes"]["plain"]["content"] == "Line 1\nLine 2"
    elif target == "opml":
        assert b'<opml' in output
    else:
        assert (b'version="freeplane ' if target == "freeplane" else b'version="1.0.1"') in output


def test_legacy_freeplane_import_preserves_non_breaking_spaces_and_literal_text():
    legacy = FREEPLANE.replace(b"Project &amp; notes", b"Project&nbsp;&amp; notes")
    legacy = legacy.replace(b"<p>Nested</p>", b"<p>Sample&nbsp;branch <![CDATA[&nbsp;]]> &amp;nbsp;</p>")
    document_format, source = convert_document_import(DocumentImportSource("legacy.mm", "", legacy))
    mindmap = MindMap.model_validate_json(source)
    assert document_format == "mindmap"
    assert mindmap.root.title == "Project\u00a0& notes"
    assert mindmap.children()["one"][0].title == "Sample\u00a0branch &nbsp; &nbsp;"


def test_invalid_inputs_cannot_execute_markup_or_be_saved_as_trees():
    with pytest.raises(ValueError, match="Invalid mind map XML"):
        import_source("unsafe.mm", "", b'<!DOCTYPE map [<!ENTITY x "unsafe">]><map><node TEXT="&x;"/></map>')
    with pytest.raises(ValueError, match="connect"):
        MindMap.model_validate_json('{"version":1,"nodes":[{"id":"root","parent":null,"title":""},{"id":"loop","parent":"loop","title":""}]}')
    with pytest.raises(ValueError, match="version"):
        MindMap.model_validate_json('{"nodes":[{"id":"root","parent":null,"title":""}]}')
    source = import_source("unsafe.mm", "", FREEPLANE.replace(b"https://example.test/resource", b"script:test"))
    assert b"script:" not in export_source(source, "freeplane")[0]


def test_existing_mind_map_import_uses_its_native_format_even_with_an_interchange_title():
    assert convert_document_import(DocumentImportSource(
        "Existing map.mm", MEDIA_TYPE, INITIAL_CONTENT.encode(), "mindmap",
    )) == ("mindmap", INITIAL_CONTENT)


def test_node_connections_survive_moves_and_are_removed_with_an_endpoint():
    source = json.loads(import_source("example.mm", "", FREEPLANE))
    nodes = source["nodes"]
    first, second = nodes[1]["id"], nodes[-1]["id"]
    link = {"source": first, "target": second, "label": "Depends on"}
    source["connectors"] = [link]
    mindmap = MindMap.model_validate(source)
    moved = apply_commands(mindmap, [MoveBranch(operation="move", node_id=first, parent_id=second)])
    assert json.loads(moved.source())["connectors"] == [link]
    removed = apply_commands(moved, [RemoveBranch(operation="remove", node_id=second)])
    assert not removed.connectors
    for invalid in (
        [{**link, "target": first}],
        [{**link, "target": "missing"}],
        [link, {**link, "source": second, "target": first}],
    ):
        with pytest.raises(ValueError, match="must link two existing nodes"):
            MindMap.model_validate({**source, "connectors": invalid})


def test_native_import_and_branch_commands_preserve_a_theme_from_a_newer_viewer():
    source = json.loads(INITIAL_CONTENT)
    source["theme"] = {"id": "future-palette", "version": 2}
    source["background_color"] = "future-color"
    mapped = import_source("map.mindmap", MEDIA_TYPE, json.dumps(source).encode())
    edited = apply_commands(MindMap.model_validate_json(mapped), [
        AddBranch(operation="add", node_id="sample", parent_id="root", title="Sample"),
    ])
    revised = json.loads(edited.source())
    assert revised["theme"] == source["theme"]
    assert revised["background_color"] == source["background_color"]


@pytest.mark.asyncio
async def test_uploaded_map_uses_normal_revisions_and_authorized_export(client):
    credentials = {"email": "synthetic-map-owner@example.com", "password": "Synthetic-map-password-123"}
    owner = await client.post("/api/auth/register", json=credentials)
    assert owner.status_code == 201, owner.text
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"], "X-Editorial-Profile-Version": "1"}
    data = {"owner_kind": "user", "owner_id": owner.json()["id"], "title": "Mind map"}
    empty = await client.post("/api/documents", headers=headers, json={**data, "document_format": "mindmap"})
    assert empty.status_code == 201, empty.text
    assert (await client.get(f"/api/documents/{empty.json()['id']}/source", headers=headers)).text == INITIAL_CONTENT

    imported = await client.post("/api/documents/import", headers=headers, data={"data": json.dumps(data)},
        files={"file": ("example.mm", FREEPLANE, "application/octet-stream")})
    assert imported.status_code == 201, imported.text
    assert imported.json()["document_format"] == "mindmap"
    path = f"/api/documents/{imported.json()['id']}"
    saved = await client.get(f"{path}/source", headers=headers)
    assert saved.status_code == 200 and saved.headers["content-type"] == MEDIA_TYPE
    updated = json.loads(saved.text)
    updated["theme"] = {"id": "ocean", "version": 1}
    updated["background_color"] = "#264851"
    updated["nodes"][0]["title"] = "Revised root"
    updated["nodes"][0]["checked"] = True
    updated["nodes"][1]["checked"] = False
    updated["nodes"][0]["value"] = "001 A"
    updated["nodes"][1]["value"] = ""
    updated["connectors"] = [{"source": updated["nodes"][1]["id"], "target": updated["nodes"][-1]["id"], "label": "Depends on"}]
    updated["nodes"][1]["body_html"] = (
        '<blockquote class="galaris-link-card" data-resource-mode="embed" data-resource-size="640x360">'
        f'<p><a href="document://{empty.json()["id"]}">Source mind map</a></p></blockquote>'
    )
    update = {"expected_revision": 1, "payload": {"text": json.dumps(updated)}}
    response = await client.patch(path, headers=headers, json=update)
    assert response.status_code == 200 and response.json()["revision"] == 2, response.text
    assert (await client.patch(path, headers=headers, json=update)).status_code == 409

    reopened = await client.get(f"{path}/source", headers=headers)
    reopened_source = json.loads(reopened.text)
    assert reopened_source["theme"] == updated["theme"]
    assert reopened_source["background_color"] == "#264851"
    assert reopened_source["connectors"] == updated["connectors"]
    nodes = reopened_source["nodes"]
    assert [node.get("checked") for node in nodes] == [True, False, None, None]
    assert [node.get("value") for node in nodes] == ["001 A", "", None, None]
    assert 'data-resource-size="640x360"' in nodes[1]["body_html"]
    previous = await client.get(f"{path}/source", headers=headers, params={"revision": 1})
    previous_source = json.loads(previous.text)
    assert "theme" not in previous_source
    assert "background_color" not in previous_source
    assert "connectors" not in previous_source
    assert all("checked" not in node for node in previous_source["nodes"])
    assert all("value" not in node for node in previous_source["nodes"])
    assert "data-resource-size" not in previous_source["nodes"][1].get("body_html", "")

    for revision, title in ((1, "Project & notes"), (2, "Revised root")):
        export = await client.get(f"{path}/source", headers=headers, params={"export_format": "opml", "revision": revision})
        assert export.status_code == 200, export.text
        assert structure(import_source("map.opml", "", export.content))[0] == title
    client.cookies.clear()
    assert (await client.get(f"{path}/source?export_format=opml")).status_code in {401, 403}


@pytest.mark.asyncio
async def test_mcp_batch_rejects_stale_revisions_unauthorized_writes_and_partial_operations(db, document_tool_agents, revision_clock):
    owner, peer = document_tool_agents
    owner_ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    peer_ctx = McpToolContext(agent_id=peer.id, runtime="internal")
    created = json.loads(await files.create_file(owner_ctx, "document://", INITIAL_CONTENT,
        name="Synthetic map", document_format="mindmap"))
    uri = created["uri"]
    read = json.loads(await files.read_file(owner_ctx, uri, selector="/nodes"))
    root, revision = json.loads(read["content"])["root_id"], read["revision"]
    chart_data = {"version": 1, "type": "bar", "title": "Trial count", "rows": [{"label": "April", "value": 8}]}
    encoded = quote(json.dumps(chart_data), safe="")
    body = (f'<p><strong>Measured result</strong></p><svg data-galaris-chart="{encoded}" height="40" width="60">'
            '<title>Trial count</title><rect height="8" width="15" x="5" y="22"></rect><text x="5" y="38">April 8</text></svg>')
    commands = [
        {"operation": "add", "node_id": "branch", "parent_id": root, "title": "Main branch", "checked": True},
        {"operation": "add", "node_id": "child", "parent_id": "branch", "title": "Child", "checked": False},
        {"operation": "edit", "node_id": "child", "title": "Edited child",
         "icon": "emoji:1F680", "body_html": body},
        {"operation": "edit", "node_id": "branch", "checked": None},
    ]

    async def edit(ctx, revision, commands):
        return json.loads(await files.edit_file(ctx, uri, content=json.dumps(commands),
            expected_revision=revision, selector="/nodes"))

    with pytest.raises(PermissionError):
        await edit(peer_ctx, revision, commands)
    with pytest.raises(PermissionError):
        await files.write_file(peer_ctx, uri, "<p>Unauthorized</p>", expected_revision=revision,
            selector="root/body_html")
    edited = await edit(owner_ctx, revision, commands)
    assert edited["revision"] == revision + 1
    await revision_clock.settle()
    node = json.loads(json.loads(await files.read_file(owner_ctx, uri, selector="child"))["content"])
    assert node["icon"] == "emoji:1F680"
    assert node["body_html"] == body
    assert node["checked"] is False
    with pytest.raises(files.FileEditRejected, match="revision conflict"):
        await edit(owner_ctx, revision, commands)

    with pytest.raises(files.FileEditRejected, match="outside"):
        await edit(owner_ctx, edited["revision"], [
            {"operation": "add", "node_id": "discarded", "parent_id": root, "title": "Never saved"},
            {"operation": "move", "node_id": "branch", "parent_id": "child"},
        ])
    unchanged = json.loads(await files.read_file(owner_ctx, uri, selector="/nodes"))
    assert unchanged["revision"] == edited["revision"]
    branches = json.loads(unchanged["content"])["nodes"][1:]
    assert [(node["id"], node["title"]) for node in branches] == [
        ("branch", "Main branch"), ("child", "Edited child"),
    ]
    assert branches[0]["checked"] is None

    from app.agent.dialogue_service import set_agent_membership
    from core.team import TeamModel

    team = TeamModel(name="Synthetic mind map editors")
    db.add(team)
    await db.flush()
    for agent in (owner, peer):
        await set_agent_membership(team.id, agent.id, True)
    connection_id = await db.scalar(select(Connection.id).join(Service).where(
        Connection.agent_id == peer.id, Service.code == "document",
    ))
    await connections.set_management_scope(connection_id, "team", authorized=True)
    with pytest.raises(resource_service.DocumentPermissionError):
        await files.read_file(peer_ctx, uri, selector="/nodes")
    grants = json.loads(await mcp.document_sharing(owner_ctx, uri))
    await mcp.document_share(owner_ctx, uri, agent_id=peer.id, access="edit",
        expected_lock_version=grants["lock_version"])
    assert json.loads(await files.read_file(peer_ctx, uri, selector="/nodes"))["revision"] == edited["revision"]
    delegated = json.loads(await mcp.document_sharing(peer_ctx, uri))
    assert delegated["can_manage"]
    shared = json.loads(await mcp.document_share(peer_ctx, uri, team_id=team.id, access="read",
        expected_lock_version=delegated["lock_version"]))
    assert ("team", team.id) in {(grant["kind"], grant["id"]) for grant in shared["grants"]}
    revised = await edit(peer_ctx, edited["revision"], [
        {"operation": "add", "node_id": "delegated", "parent_id": root, "title": "Delegated branch"},
    ])
    assert revised["revision"] == edited["revision"] + 1
    await set_agent_membership(team.id, owner.id, False)
    with pytest.raises(PermissionError):
        await files.read_file(peer_ctx, uri, selector="/nodes")
    with pytest.raises(PermissionError):
        await mcp.document_sharing(peer_ctx, uri)
    await connections.set_management_scope(connection_id, "all", authorized=True)
    assert json.loads(await files.read_file(peer_ctx, uri, selector="/nodes"))["revision"] == revised["revision"]

    revised_body = "<p>New branch content.</p>"
    written = json.loads(await files.write_file(peer_ctx, uri, revised_body,
        expected_revision=revised["revision"], selector="child/body_html"))
    assert written["revision"] == revised["revision"] + 1
    first = json.loads(await files.read_file(owner_ctx, uri, max_chars=8, selector="child/body_html"))
    second = json.loads(await files.read_file(owner_ctx, uri, offset=first["next_offset"],
        revision=first["revision"], selector=first["selector"]))
    assert first["content"] + second["content"] == revised_body
    assert first["media_type"] == "text/html" and first["revision"] == written["revision"]
    previous = json.loads(await files.read_file(owner_ctx, uri, revision=edited["revision"], selector="child/body_html"))
    assert previous["content"] == body
    with pytest.raises(resource_service.DocumentConflictError, match="revision conflict"):
        await files.write_file(peer_ctx, uri, "<p>Stale content</p>", expected_revision=revised["revision"],
            selector="child/body_html")
    with pytest.raises(ValueError, match="does not exist"):
        await files.write_file(peer_ctx, uri, "<p>Missing branch</p>", expected_revision=written["revision"],
            selector="absent/body_html")
    node = json.loads(json.loads(await files.read_file(owner_ctx, uri, selector="child"))["content"])
    node["title"] = "Renamed child"
    renamed = json.loads(await files.write_file(owner_ctx, uri, json.dumps(node),
        expected_revision=written["revision"], selector="child"))
    assert renamed["revision"] == written["revision"] + 1
    complete = json.loads(await files.read_file(owner_ctx, uri))
    assert complete["revision"] == renamed["revision"]
    assert [(node["id"], node["title"]) for node in json.loads(complete["content"])["nodes"]] == [
        (root, ""), ("branch", "Main branch"), ("child", "Renamed child"), ("delegated", "Delegated branch"),
    ]


@pytest.mark.asyncio
async def test_mcp_missing_branch_explains_how_to_add_it(db, agents):
    owner, _ = agents
    await sync_integrated_service_connections(owner.id)
    connection_id = await db.scalar(select(Connection.id).join(Service).where(
        Connection.agent_id == owner.id, Service.code == "file_sharing",
    ))
    assert connection_id is not None
    for name in ("file_edit", "file_write"):
        await connections.set_connection_function_state(connection_id, name, "enabled")
    owner_ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    created = json.loads(await files.create_file(owner_ctx, "document://", INITIAL_CONTENT,
        name="Synthetic map", document_format="mindmap"))
    root = "root"
    await db.commit()
    server = build_galaris_fastmcp(owner.id, enabled_service_codes={"document", "file_sharing"})
    arguments = {"uri": created["uri"], "expected_revision": created["revision"], "selector": "/nodes"}

    async with Client(server) as client:
        assert not any(tool.name.startswith("mindmap_") for tool in await client.list_tools())
        compiled = await client.call_tool("document_chart", {"chart_type": "bar",
            "rows": [{"label": "Trial & review", "value": 8}]})
        chart = json.loads(compiled.content[0].text)["html"]
        assert "Trial &amp; review" in chart and "<svg" not in chart
        invalid = await client.call_tool("document_chart", {"chart_type": "pie",
            "rows": [{"label": "Trial", "value": -8}]}, raise_on_error=False)
        assert invalid.is_error
        assert invalid.meta[EXECUTION_META_KEY]["outcome"] == "rejected"

        result = await client.call_tool("file_edit", {**arguments, "content": json.dumps([
            {"operation": "edit", "node_id": "appendix"},
        ])}, raise_on_error=False)
        assert result.is_error
        assert result.meta[EXECUTION_META_KEY]["outcome"] == "rejected"
        assert "appendix" in result.content[0].text
        assert "operation='add'" in result.content[0].text

        empty_edit = await client.call_tool("file_edit", {**arguments, "content": json.dumps([
            {"operation": "edit", "node_id": root},
        ])}, raise_on_error=False)
        assert empty_edit.is_error
        assert empty_edit.meta[EXECUTION_META_KEY]["outcome"] == "rejected"
        assert "field to change" in empty_edit.content[0].text

        added = await client.call_tool("file_edit", {**arguments, "content": json.dumps([
            {"operation": "add", "node_id": "appendix", "parent_id": root, "title": "Appendix", "body_html": chart},
            {"operation": "add", "node_id": "sources", "parent_id": "appendix", "title": "Sources"},
        ])})
        assert json.loads(added.content[0].text)["revision"] == created["revision"] + 1
        stale = await client.call_tool("file_edit", {**arguments, "content": json.dumps([
            {"operation": "add", "node_id": "stale", "parent_id": root, "title": "Stale"},
        ])}, raise_on_error=False)
        assert stale.is_error
        assert "revision conflict" in stale.content[0].text

    saved = json.loads(await files.read_file(owner_ctx, created["uri"]))
    branch = json.loads(json.loads(await files.read_file(owner_ctx, created["uri"], selector="appendix"))["content"])
    assert branch["body_html"] == chart
    assert saved["revision"] == created["revision"] + 1
    assert [(node["id"], node["parent"]) for node in json.loads(saved["content"])["nodes"]] == [
        (root, None), ("appendix", root), ("sources", "appendix"),
    ]


@pytest.mark.asyncio
async def test_rich_node_preserves_attachment_reference_and_controls_inline_image_ownership(client, memory_storage):
    credentials = {"email": "synthetic-rich-map@example.com", "password": "Synthetic-map-password-123"}
    owner = await client.post("/api/auth/register", json=credentials)
    assert owner.status_code == 201, owner.text
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"], "X-Editorial-Profile-Version": "1"}
    common = {"owner_kind": "user", "owner_id": owner.json()["id"]}
    created = await client.post("/api/documents", headers=headers, json={**common, "title": "Map", "document_format": "mindmap"})
    other = await client.post("/api/documents", headers=headers, json={**common, "title": "Measurements"})
    assert created.status_code == other.status_code == 201, (created.text, other.text)
    map_id, other_id = created.json()["id"], other.json()["id"]
    path = f"/api/documents/{map_id}"

    pixels = BytesIO()
    with Image.new("RGB", (2, 2), "white") as image:
        image.save(pixels, format="PNG")

    async def upload(document_id):
        result = await client.post(f"/api/documents/{document_id}/attachments", headers=headers,
            files={"file": ("sample.png", pixels.getvalue(), "image/png")})
        assert result.status_code == 201, result.text
        return f"document://{document_id}/attachments/{result.json()['id']}"

    own_image, foreign_image = await upload(map_id), await upload(other_id)

    def update(image):
        value = json.loads(INITIAL_CONTENT)
        value["nodes"][0]["body_html"] = f'<p><strong>Evidence</strong> <a href="{foreign_image}">Source file</a></p><img src="{image}">'
        return {"expected_revision": 1, "payload": {"text": json.dumps(value)}}

    denied = await client.patch(path, headers=headers, json=update(foreign_image))
    assert denied.status_code == 403, denied.text
    saved = await client.patch(path, headers=headers, json=update(own_image))
    assert saved.status_code == 200 and saved.json()["revision"] == 2, saved.text
    saved_source = await client.get(f"{path}/source", headers=headers)
    body = json.loads(saved_source.text)["nodes"][0]["body_html"]
    assert f'href="{foreign_image}"' in body and f'src="{own_image}"' in body
    assert own_image in saved.json()["metadata"]["content_images"]
