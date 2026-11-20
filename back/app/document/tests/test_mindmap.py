"""Mind map interchange and revision-preserving branch editing."""

from io import BytesIO
import json
from zipfile import ZipFile

from PIL import Image
import pytest
from pydantic import TypeAdapter

from app.document import mcp, resource_service
from app.document.file_import import DocumentImportSource, convert_document_import
from app.document.mindmap import INITIAL_CONTENT, MindMap
from app.document.mindmap.commands import AddBranch, BranchCommand, MoveBranch, RemoveBranch, apply_commands
from app.document.mindmap.exchange import MEDIA_TYPE, export_source, import_source
from app.services import McpToolContext


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
async def test_mcp_batch_rejects_stale_revisions_unauthorized_writes_and_partial_operations(db, agents):
    owner, peer = agents
    owner_ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    peer_ctx = McpToolContext(agent_id=peer.id, runtime="internal")
    created = json.loads(await mcp.mindmap_create(owner_ctx, title="Synthetic map"))
    uri = created["uri"]
    assert created["root_id"] == "root"
    read = json.loads(await mcp.mindmap_read(owner_ctx, uri))
    root, revision = read["root_id"], read["revision"]
    commands = TypeAdapter(list[BranchCommand]).validate_python([
        {"operation": "add", "node_id": "branch", "parent_id": root, "title": "Main branch", "checked": True},
        {"operation": "add", "node_id": "child", "parent_id": "branch", "title": "Child", "checked": False},
        {"operation": "edit", "node_id": "child", "title": "Edited child",
         "icon": "emoji:1F680", "body_html": "<p><strong>Measured result</strong></p>"},
        {"operation": "edit", "node_id": "branch", "checked": None},
    ])
    with pytest.raises(resource_service.DocumentPermissionError):
        await mcp.mindmap_edit(peer_ctx, uri, revision, commands)
    edited = json.loads(await mcp.mindmap_edit(owner_ctx, uri, revision, commands))
    assert edited["revision"] == revision + 1 and edited["total"] == 3
    node = json.loads(await mcp.mindmap_read(owner_ctx, uri, node_id="child"))["node"]
    assert node["icon"] == "emoji:1F680"
    assert node["body_html"] == "<p><strong>Measured result</strong></p>"
    assert node["checked"] is False
    with pytest.raises(resource_service.DocumentConflictError):
        await mcp.mindmap_edit(owner_ctx, uri, revision, commands)

    with pytest.raises(ValueError, match="outside"):
        await mcp.mindmap_edit(owner_ctx, uri, edited["revision"], [
            AddBranch(operation="add", node_id="discarded", parent_id=root, title="Never saved"),
            MoveBranch(operation="move", node_id="branch", parent_id="child"),
        ])
    unchanged = json.loads(await mcp.mindmap_read(owner_ctx, uri, offset=1, limit=2))
    assert unchanged["revision"] == edited["revision"]
    assert [(node["id"], node["title"]) for node in unchanged["nodes"]] == [
        ("branch", "Main branch"), ("child", "Edited child"),
    ]
    assert unchanged["nodes"][0]["checked"] is None


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
