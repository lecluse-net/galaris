"""ZIP preparation preserves paths and bytes before any document is created."""

from email import policy
from email.parser import BytesParser
from io import BytesIO
import json
import stat
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import pytest

from app.document.archive_import import archive_parts, prepare_archive


def archive_bytes(entries):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def multipart(content_type, content):
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + content)
    return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in message.iter_parts()}


def test_archive_expansion_keeps_implicit_empty_directories_and_every_file():
    source = archive_bytes([("empty/", b""), ("notes/deep/report.md", b"# Synthetic report"),
                            ("notes/values.json", b'{"value":42}'), ("notes/nested.zip", b"synthetic opaque bytes")])
    prepared = prepare_archive(source)
    parts = multipart(f"multipart/form-data; boundary={prepared.boundary}", b"".join(archive_parts(prepared)))
    manifest = json.loads(parts["manifest"])
    assert manifest["directories"] == ["empty", "notes", "notes/deep"]
    assert {file["path"]: parts[file["key"]] for file in manifest["files"]} == {
        "notes/deep/report.md": b"# Synthetic report", "notes/values.json": b'{"value":42}',
        "notes/nested.zip": b"synthetic opaque bytes"}


@pytest.mark.parametrize("paths", [
    ["../escape.txt"], ["/absolute.txt"], ["C:/drive.txt"], ["a/../escape.txt"], ["a//b.txt"],
    ["duplicate.txt", "duplicate.txt"], ["parent", "parent/child.txt"], ["/"],
    ["a" * 101 + "/file.txt"], ["/".join(["deep"] * 33) + "/file.txt"],
])
def test_archive_rejects_ambiguous_or_unsafe_hierarchies(paths):
    with pytest.raises(ValueError):
        prepare_archive(archive_bytes([(path, b"synthetic") for path in paths]))


def test_archive_rejects_symlinks_corruption_and_expansion_bombs(monkeypatch):
    from core.params import runtime_settings
    link = ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="special"):
        prepare_archive(archive_bytes([(link, b"target")]))
    damaged = bytearray(archive_bytes([("source.txt", b"synthetic text")]))
    damaged[40] ^= 0xFF
    with pytest.raises(ValueError):
        prepare_archive(bytes(damaged))
    monkeypatch.setattr(runtime_settings, "MEMORY_RESOURCE_MAX_BYTES", 1024)
    with pytest.raises(ValueError, match="Expanded ZIP"):
        prepare_archive(archive_bytes([("large.txt", b"x" * 5000)]))


@pytest.mark.asyncio
async def test_archive_http_expansion_is_authorized_and_does_not_create_resources(client):
    source = archive_bytes([("nested/report.md", b"# Synthetic report"), ("empty/", b"")])
    upload = {"file": ("Synthetic archive.zip", source, "application/zip")}
    data = {"data": "{}"}
    path = "/api/documents/import-archive"
    assert (await client.post(path, data=data, files=upload)).status_code == 401
    credentials = {"email": "synthetic-archive-owner@example.com", "password": "Synthetic-archive-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": "Bearer " + login.json()["access_token"], "X-Editorial-Profile-Version": "1"}
    result = await client.post(path, data=data, files=upload, headers=headers)
    assert result.status_code == 200, result.text
    parts = multipart(result.headers["content-type"], result.content)
    manifest = json.loads(parts["manifest"])
    assert manifest["directories"] == ["empty", "nested"]
    assert parts[manifest["files"][0]["key"]] == b"# Synthetic report"
    tags = await client.get("/api/documents/tags", headers=headers)
    assert tags.json()["tags"] == []
    library = await client.post("/api/documents/library", headers=headers, json={"classification": "all"})
    assert library.json()["total"] == 0
