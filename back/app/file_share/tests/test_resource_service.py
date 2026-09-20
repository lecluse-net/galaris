from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.file_share import resource_service
from app.file_share.file_contracts import FileEntry, FileMutation
from app.file_share.messenger_transport import MessengerFileTransport
from app.file_share.resource_contracts import ResourceContext, ResourceDescriptor
from .local_file_transport import TemporaryFileTransport


@pytest.mark.asyncio
async def test_messenger_upload_failure_leaves_no_receipt_and_explicit_resend_remains_possible(db, monkeypatch):
    from app.task import Task, parse_working_set

    task = Task(label="Generate file")
    db.add(task)
    await db.flush()
    room = SimpleNamespace(id=uuid4(), external_id="provider-room", connection_id=7)
    uploads = []
    fail = True
    class Messenger:
        async def upload_file_path(self, destination, path, filename):
            if fail:
                raise OSError("transport unavailable")
            uploads.append(path.read_bytes())
            return SimpleNamespace(id=uuid4(), room=room,
                                   files=[SimpleNamespace(id=uuid4(), name=filename)])
    async def resolve(*args, **kwargs):
        return MessengerFileTransport(Messenger()), "messenger"
    monkeypatch.setattr(resource_service, "resolve_resource_transport_with_service", resolve)
    ctx = ResourceContext(agent_id=1, runtime="hermes", task_id=task.id)
    with pytest.raises(OSError):
        await resource_service.resource_create(ctx, "chat://provider-room/image.png", b"image")
    assert parse_working_set(task).resources == []
    fail = False
    first = await resource_service.resource_create(ctx, "chat://provider-room/image.png", b"image")
    second = await resource_service.resource_create(ctx, "chat://provider-room/image.png", b"image")
    await db.commit()
    await db.refresh(task)
    assert len(uploads) == 2
    assert first.uri != second.uri
    assert {item.reference for item in parse_working_set(task).active()} == {first.uri, second.uri}


@pytest.fixture()
def resource_console(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[TemporaryFileTransport]:
    transport = TemporaryFileTransport(tmp_path / "console")

    async def resolve(_ctx: ResourceContext) -> TemporaryFileTransport:
        return transport

    monkeypatch.setattr(resource_service, "_console_transport", resolve)
    yield transport


@pytest.mark.asyncio
async def test_uri_file_operations_share_one_console_contract(
    resource_console: TemporaryFileTransport,
) -> None:
    ctx = ResourceContext(agent_id=1, runtime="internal", console_resource=object())

    written = await resource_service.resource_write_text(
        ctx,
        "console://notes/source.md",
        "Alpha and Beta",
    )
    copied = await resource_service.resource_copy(
        ctx,
        written.uri,
        "console://archive/",
    )
    listing = await resource_service.resource_list(
        ctx,
        "console://",
        recursive=True,
    )
    search = await resource_service.resource_search(
        ctx,
        "console://",
        "Beta",
        mode="text",
    )
    read = await resource_service.resource_read(ctx, copied.uri)

    assert written.uri == "console://notes/source.md"
    assert copied.uri == "console://archive/source.md"
    assert {entry.uri for entry in listing.entries} >= {
        "console://notes/source.md",
        "console://archive/source.md",
    }
    assert [hit.resource.uri for hit in search.hits] == [
        "console://archive/source.md",
        "console://notes/source.md",
    ]
    assert read.content == "Alpha and Beta"

    moved = await resource_service.resource_move(
        ctx,
        copied.uri,
        "console://archive/final.md",
    )
    deleted = await resource_service.resource_delete(ctx, moved.uri)

    assert moved.moved is True
    assert deleted.state == "deleted"
    assert not resource_console.resolve_path(
        "archive/final.md", create_parent=False
    ).exists()


@pytest.mark.asyncio
async def test_console_scheme_handles_local_copy_and_move(
    resource_console: TemporaryFileTransport,
) -> None:
    ctx = ResourceContext(
        agent_id=1,
        runtime="internal",
        console_resource=object(),
    )
    created = await resource_service.resource_write_text(
        ctx,
        "console://work/source.txt",
        "from ssh home",
    )
    downloaded = await resource_service.resource_copy(
        ctx,
        created.uri,
        "console://imports/",
    )
    uploaded = await resource_service.resource_copy(
        ctx,
        downloaded.uri,
        "console://processed/",
    )
    moved = await resource_service.resource_move(
        ctx,
        uploaded.uri,
        "console://processed/final.txt",
    )
    listing = await resource_service.resource_list(
        ctx,
        "console://",
        recursive=True,
    )
    read = await resource_service.resource_read(ctx, moved.uri)

    assert created.uri == "console://work/source.txt"
    assert downloaded.uri == "console://imports/source.txt"
    assert uploaded.uri == "console://processed/source.txt"
    assert moved.uri == "console://processed/final.txt"
    assert listing.uri == "console://"
    assert {entry.uri for entry in listing.entries} >= {
        "console://work/source.txt",
        "console://processed/final.txt",
    }
    assert read.content == "from ssh home"
    assert resource_console.resolve_path(
        "processed/final.txt", create_parent=False
    ).read_text() == "from ssh home"
    assert resource_console.resolve_path(
        "imports/source.txt", create_parent=False
    ).read_text() == "from ssh home"

    deleted = await resource_service.resource_delete(ctx, moved.uri)
    assert deleted.uri == "console://processed/final.txt"
    assert not resource_console.resolve_path(
        "processed/final.txt", create_parent=False
    ).exists()


@pytest.mark.asyncio
async def test_console_create_write_and_collection_move_keep_home_relative_uris(
    resource_console: TemporaryFileTransport,
) -> None:
    ctx = ResourceContext(
        agent_id=1,
        runtime="internal",
        console_resource=object(),
    )

    created = await resource_service.resource_create(
        ctx,
        "console://mon_fichier.txt",
        b"first",
    )
    written = await resource_service.resource_write(
        ctx,
        created.uri,
        b"second",
    )
    moved = await resource_service.resource_move(
        ctx,
        written.uri,
        "console://archive/",
    )

    assert created.uri == "console://mon_fichier.txt"
    assert written.uri == "console://mon_fichier.txt"
    assert moved.uri == "console://archive/mon_fichier.txt"
    assert resource_console.resolve_path(
        "archive/mon_fichier.txt", create_parent=False
    ).read_bytes() == b"second"
    assert not resource_console.resolve_path(
        "mon_fichier.txt", create_parent=False
    ).exists()


@pytest.mark.asyncio
async def test_console_copy_and_move_detect_existing_collections_without_slash(
    resource_console: TemporaryFileTransport,
) -> None:
    ctx = ResourceContext(
        agent_id=1,
        runtime="internal",
        console_resource=object(),
    )
    await resource_service.resource_create(
        ctx,
        "console://source.txt",
        b"content",
    )
    resource_console.resolve_path("copies", create_parent=False).mkdir()
    resource_console.resolve_path("archive", create_parent=False).mkdir()

    copied = await resource_service.resource_copy(
        ctx,
        "console://source.txt",
        "console://copies",
    )
    exact = await resource_service.resource_copy(
        ctx,
        "console://source.txt",
        "console://extensionless-copy",
    )
    moved = await resource_service.resource_move(
        ctx,
        copied.uri,
        "console://archive",
    )

    assert copied.uri == "console://copies/source.txt"
    assert exact.uri == "console://extensionless-copy"
    assert moved.uri == "console://archive/source.txt"
    assert resource_console.resolve_path(
        "archive/source.txt", create_parent=False
    ).read_bytes() == b"content"
    assert not resource_console.resolve_path(
        "copies/source.txt", create_parent=False
    ).exists()


@pytest.mark.asyncio
async def test_copy_to_affine_workspace_uses_source_name_without_destination_file(
    resource_console: TemporaryFileTransport,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = ResourceContext(
        agent_id=1,
        runtime="internal",
        console_resource=object(),
    )
    affine = TemporaryFileTransport(tmp_path / "affine")
    await resource_service.resource_create(
        ctx,
        "console://report.pdf",
        b"pdf",
    )

    async def resolve(
        _agent_id: int,
        tool_code: str,
        locator: str,
        *,
        language: str | None = None,
    ) -> tuple[TemporaryFileTransport, str]:
        del language
        assert tool_code == "affine"
        assert locator in {"workspace-42", "workspace-42/report.pdf"}
        return affine, "affine"

    monkeypatch.setattr(
        resource_service,
        "resolve_resource_transport_with_service",
        resolve,
    )

    copied = await resource_service.resource_copy(
        ctx,
        "console://report.pdf",
        "affine://workspace-42",
    )

    assert copied.uri == "affine://workspace-42/report.pdf"
    assert affine.resolve_path(
        "report.pdf", "workspace-42", create_parent=False
    ).read_bytes() == b"pdf"


@pytest.mark.asyncio
async def test_connected_move_detects_existing_collection_without_slash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class NextcloudProvider(TemporaryFileTransport):
        async def resource_info(
            self,
            path: str,
            *,
            include_sha256: bool = False,
        ) -> FileEntry:
            return await self.file_info(path, include_sha256=include_sha256)

        async def resource_copy(
            self,
            source: str,
            destination: str,
            *,
            overwrite: bool,
        ) -> FileMutation:
            if not overwrite:
                try:
                    await self.file_info(destination, include_sha256=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(destination)
            return await self.file_copy(source, destination)

        async def resource_move(
            self,
            source: str,
            destination: str,
            *,
            overwrite: bool,
        ) -> FileMutation:
            if not overwrite:
                try:
                    await self.file_info(destination, include_sha256=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(destination)
            return await self.file_move(source, destination)

    provider = NextcloudProvider(tmp_path / "nextcloud")
    provider.resolve_path("source.txt").write_bytes(b"content")
    provider.resolve_path("Shared", create_parent=False).mkdir()

    async def resolve(
        _agent_id: int,
        tool_code: str,
        locator: str,
        *,
        language: str | None = None,
    ) -> tuple[NextcloudProvider, str]:
        del language
        assert tool_code == "nextcloud"
        assert locator in {"source.txt", "Shared"}
        return provider, "nextcloud"

    monkeypatch.setattr(
        resource_service,
        "resolve_resource_transport_with_service",
        resolve,
    )

    moved = await resource_service.resource_move(
        ResourceContext(agent_id=1, runtime="internal"),
        "nextcloud://source.txt",
        "nextcloud://Shared",
    )

    assert moved.uri == "nextcloud://Shared/source.txt"
    assert provider.resolve_path(
        "Shared/source.txt", create_parent=False
    ).read_bytes() == b"content"
    assert not provider.resolve_path("source.txt", create_parent=False).exists()


@pytest.mark.asyncio
async def test_move_rejects_an_immutable_source_before_copying() -> None:
    ctx = ResourceContext(agent_id=1, runtime="internal")

    with pytest.raises(PermissionError, match="use file_copy instead"):
        await resource_service.resource_move(
            ctx,
            f"document://{uuid4()}",
            "console://export.md",
        )


@pytest.mark.asyncio
async def test_console_is_the_only_advertised_local_scheme_with_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_targets(
        *_args: object,
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(resource_service, "describe_targets", no_targets)

    schemes = await resource_service.list_schemes(
        ResourceContext(
            agent_id=1,
            runtime="internal",
            console_resource=object(),
        )
    )
    by_scheme = {item.scheme: item for item in schemes}
    console = by_scheme["console"]

    assert console.example == "console://reports/result.pdf"
    assert console.label == "Local files (SSH console home)"
    assert "workspace" not in by_scheme
    assert set(console.capabilities) == {
        "append",
        "copy",
        "create",
        "delete",
        "edit",
        "info",
        "list",
        "move",
        "read",
        "search",
        "write",
    }


@pytest.mark.asyncio
async def test_galaris_json_resource_can_be_copied_to_console(
    resource_console: TemporaryFileTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.task as task

    identifier = uuid4()

    async def read_task_resource(
        task_id: object,
        *,
        actor_agent_id: int,
    ) -> dict[str, object]:
        assert task_id == identifier
        assert actor_agent_id == 1
        return {
            "id": str(identifier),
            "revision": 2,
            "label": "Release / unsafe filename",
            "status": "SUCCESS",
            "snapshot": "x" * (resource_service._TEXT_WRITE_LIMIT + 1),
        }

    monkeypatch.setattr(task, "read_task_resource", read_task_resource)
    result = await resource_service.resource_copy(
        ResourceContext(agent_id=1, runtime="internal", console_resource=object()),
        f"galaris://task/{identifier}",
        "console://exports/",
    )

    assert result.uri == f"console://exports/task-{identifier}.json"
    exported = resource_console.resolve_path(
        f"exports/task-{identifier}.json",
        create_parent=False,
    )
    assert '"label": "Release / unsafe filename"' in exported.read_text()
    assert exported.stat().st_size > resource_service._TEXT_WRITE_LIMIT


@pytest.mark.asyncio
async def test_scheme_listing_uses_connected_tool_codes_not_capability_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def targets(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "code": "telegram-bot",
                "service": "messenger",
                "label": "Telegram bot",
                "description": "",
                "has_file_share": False,
                "has_messenger": True,
            },
            {
                "code": "nextcloud",
                "service": "nextcloud",
                "label": "Nextcloud",
                "description": "",
                "has_file_share": True,
                "has_messenger": True,
            },
        ]

    monkeypatch.setattr(resource_service, "describe_targets", targets)

    schemes = await resource_service.list_schemes(
        ResourceContext(agent_id=1, runtime="internal")
    )
    by_scheme = {item.scheme: item for item in schemes}

    assert "messenger" not in by_scheme
    assert "workspace" not in by_scheme
    assert "console" not in by_scheme
    assert by_scheme["telegram-bot"].example == (
        "telegram-bot://<room-id>/<attachment-id>"
    )
    assert by_scheme["nextcloud"].scheme == "nextcloud"


def test_preferred_local_uri_uses_console_only_when_available() -> None:
    assert resource_service.preferred_local_resource_uri(
        ResourceContext(agent_id=1, runtime="internal", console_resource=object()),
        "reports/result.pdf",
    ) == "console://reports/result.pdf"
    with pytest.raises(RuntimeError, match="No local filesystem"):
        resource_service.preferred_local_resource_uri(
            ResourceContext(agent_id=1, runtime="hermes"),
            "reports/result.pdf",
        )


@pytest.mark.asyncio
async def test_messenger_copy_uses_the_pinned_transport_and_visible_filename(
    resource_console: TemporaryFileTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment_id = uuid4()
    room_id = uuid4()
    attachment = SimpleNamespace(
        id=attachment_id,
        name="received-report.pdf",
        mime_type="application/pdf",
        size_bytes=7,
    )
    message = SimpleNamespace(
        room=SimpleNamespace(id=room_id, external_id="talk-token"),
        files=[attachment],
    )

    class PinnedMessenger:
        async def history(self, requested_room: str, _limit: int) -> list[object]:
            assert requested_room == "talk-token"
            return [message]

        async def fetch_attachment_to_file(
            self,
            requested_attachment: object,
            destination: Path,
            *, max_bytes: int = 512 * 1024 * 1024,
        ) -> int:
            assert requested_attachment is attachment
            destination.write_bytes(b"content")
            return 7

    transport = MessengerFileTransport(PinnedMessenger())

    async def connected(
        _ctx: ResourceContext,
        _reference: object,
    ) -> tuple[MessengerFileTransport, str, str, str]:
        return transport, "messenger", str(attachment_id), "talk-token"

    monkeypatch.setattr(resource_service, "_connected_transport", connected)

    result = await resource_service.resource_copy(
        ResourceContext(
            agent_id=1,
            runtime="internal",
            console_resource=object(),
        ),
        f"nextcloud://talk-token/{attachment_id}",
        "console://inbox/",
    )

    assert result.uri == "console://inbox/received-report.pdf"
    assert resource_console.resolve_path(
        "inbox/received-report.pdf",
        create_parent=False,
    ).read_bytes() == b"content"


@pytest.mark.asyncio
async def test_connected_copy_to_collection_keeps_provider_original_filename(
    resource_console: TemporaryFileTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OpaqueProvider:
        async def download_to(
            self,
            remote: str,
            destination: Path,
            *,
            target: str = "",
        ) -> int:
            assert (remote, target) == ("opaque-file-42", "")
            destination.write_bytes(b"content")
            return 7

    provider = OpaqueProvider()

    async def connected(
        _ctx: ResourceContext,
        _reference: object,
    ) -> tuple[OpaqueProvider, str, str, str]:
        return provider, "nextcloud", "opaque-file-42", ""

    async def info(
        _ctx: ResourceContext,
        _uri: object,
        *,
        include_checksum: bool = False,
    ) -> ResourceDescriptor:
        assert include_checksum is False
        return ResourceDescriptor(
            uri="nextcloud://opaque-file-42",
            name="photo originale.png",
            media_type="image/png",
            size=7,
        )

    monkeypatch.setattr(resource_service, "_connected_transport", connected)
    monkeypatch.setattr(resource_service, "resource_info", info)

    result = await resource_service.resource_copy(
        ResourceContext(agent_id=1, runtime="internal", console_resource=object()),
        "nextcloud://opaque-file-42",
        "console://inbox/",
    )

    assert result.uri == "console://inbox/photo%20originale.png"
    assert resource_console.resolve_path(
        "inbox/photo originale.png", create_parent=False
    ).read_bytes() == b"content"


@pytest.mark.asyncio
async def test_resource_write_requires_explicit_overwrite(
    resource_console: TemporaryFileTransport,
) -> None:
    del resource_console
    ctx = ResourceContext(agent_id=1, runtime="internal", console_resource=object())
    await resource_service.resource_write_text(ctx, "console://same.txt", "first")

    with pytest.raises(FileExistsError):
        await resource_service.resource_write_text(
            ctx, "console://same.txt", "second"
        )

    result = await resource_service.resource_write_text(
        ctx,
        "console://same.txt",
        "second",
        overwrite=True,
    )
    assert result.state == "written"


@pytest.mark.asyncio
async def test_resource_write_replaces_one_complete_binary_file(
    resource_console: TemporaryFileTransport,
) -> None:
    ctx = ResourceContext(agent_id=1, runtime="internal", console_resource=object())
    content = b"\x00Galaris\xff\x10"

    written = await resource_service.resource_create(
        ctx,
        "console://artifacts/payload.bin",
        content,
    )

    assert written.uri == "console://artifacts/payload.bin"
    assert written.size == len(content)
    assert resource_console.resolve_path(
        "artifacts/payload.bin",
        create_parent=False,
    ).read_bytes() == content
    with pytest.raises(FileExistsError):
        await resource_service.resource_create(
            ctx,
            "console://artifacts/payload.bin",
            b"replacement",
        )

    replaced = await resource_service.resource_write(
        ctx,
        "console://artifacts/payload.bin",
        b"replacement",
    )
    assert replaced.size == len(b"replacement")
    assert resource_console.resolve_path(
        "artifacts/payload.bin",
        create_parent=False,
    ).read_bytes() == b"replacement"


@pytest.mark.asyncio
async def test_resource_read_detects_text_and_small_binary(
    resource_console: TemporaryFileTransport,
) -> None:
    ctx = ResourceContext(agent_id=1, runtime="internal", console_resource=object())
    await resource_service.resource_create(
        ctx, "console://notes/readme.txt", "héllo".encode()
    )
    await resource_service.resource_create(
        ctx, "console://images/sample.bin", b"\x00\xff\x10"
    )

    text = await resource_service.resource_read(ctx, "console://notes/readme.txt")
    binary = await resource_service.resource_read(ctx, "console://images/sample.bin")

    assert (text.encoding, text.content, text.media_type) == (
        "utf-8",
        "héllo",
        "text/plain",
    )
    assert binary.encoding == "base64"
    assert binary.content == "AP8Q"
    assert binary.total == 3


@pytest.mark.asyncio
async def test_resource_read_rejects_large_binary_with_console_guidance(
    resource_console: TemporaryFileTransport,
) -> None:
    del resource_console
    ctx = ResourceContext(agent_id=1, runtime="internal", console_resource=object())
    await resource_service.resource_create(
        ctx,
        "console://large.bin",
        b"\x00" * (resource_service._BINARY_READ_LIMIT + 1),
    )

    with pytest.raises(ValueError, match="console software"):
        await resource_service.resource_read(ctx, "console://large.bin")


@pytest.mark.asyncio
async def test_resource_create_assigns_a_document_uri_without_a_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.memory as memory

    identifier = uuid4()
    captured: dict[str, object] = {}

    async def create_document(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"id": str(identifier), "size": 5, "revision": 1}

    monkeypatch.setattr(memory, "create_document_file_resource", create_document)

    created = await resource_service.resource_create(
        ResourceContext(agent_id=9, runtime="internal"),
        "document://",
        b"draft",
    )

    assert created.uri == f"document://{identifier}"
    assert created.operation == "create"
    assert captured == {
        "agent_id": 9,
        "task_id": None,
        "title": "Document",
        "content": "draft",
        "document_type": "html",
    }


@pytest.mark.asyncio
async def test_resource_edit_replaces_one_inclusive_text_line_range(
    resource_console: TemporaryFileTransport,
) -> None:
    ctx = ResourceContext(agent_id=1, runtime="internal", console_resource=object())
    await resource_service.resource_create(
        ctx,
        "console://plan.md",
        b"one\ntwo\nthree\nfour\nfive\n",
    )

    edited = await resource_service.resource_edit(
        ctx,
        "console://plan.md",
        start_line=2,
        end_line=4,
        content="new two\nnew three",
    )
    read = await resource_service.resource_read(ctx, edited.uri)

    assert edited.operation == "edit"
    assert read.content == "one\nnew two\nnew three\nfive\n"

    with pytest.raises(ValueError, match="exceeds"):
        await resource_service.resource_edit(
            ctx,
            "console://plan.md",
            start_line=10,
            end_line=12,
            content="impossible",
        )


@pytest.mark.asyncio
async def test_canonical_percent_encoding_maps_to_decoded_console_name(
    resource_console: TemporaryFileTransport,
) -> None:
    result = await resource_service.resource_write_text(
        ResourceContext(agent_id=1, runtime="internal", console_resource=object()),
        "console://Équipe/rapport final.md",
        "ok",
    )

    assert result.uri == "console://%C3%89quipe/rapport%20final.md"
    assert resource_console.resolve_path(
        "Équipe/rapport final.md", create_parent=False
    ).read_text() == "ok"
    assert not resource_console.resolve_path(
        "%C3%89quipe/rapport%20final.md", create_parent=False
    ).exists()


@pytest.mark.asyncio
async def test_document_collection_lists_canonical_resource_uris(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.memory as memory

    identifier = uuid4()

    async def search(**_kwargs: object) -> dict[str, object]:
        return {
            "hits": [
                {
                    "id": str(identifier),
                    "title": "Release notes",
                    "filename": "release.md",
                    "media_type": "text/markdown",
                    "size": 42,
                    "revision": 3,
                    "checksum": "abc",
                    "updated_at": None,
                    "can_write": True,
                    "metadata": {},
                }
            ],
            "has_more": False,
            "next_offset": None,
        }

    monkeypatch.setattr(memory, "search_file_resources", search)

    result = await resource_service.resource_list(
        ResourceContext(agent_id=1, runtime="internal"),
        "document://",
    )

    assert [entry.uri for entry in result.entries] == [f"document://{identifier}"]
    assert {"read", "write", "append", "edit"} <= set(
        result.entries[0].capabilities
    )


@pytest.mark.asyncio
async def test_memory_search_uses_canonical_recall_and_configured_limit_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.memory as memory

    captured: dict[str, object] = {}

    async def search(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"hits": [], "has_more": False, "next_offset": None}

    monkeypatch.setattr(memory, "search_file_resources", search)

    result = await resource_service.resource_search(
        ResourceContext(agent_id=1, runtime="internal"),
        "memory://",
        "deployment decisions",
        mode="semantic",
    )

    assert result.hits == []
    assert captured["mode"] == "semantic"
    assert captured["limit"] is None

    await resource_service.resource_search(
        ResourceContext(agent_id=1, runtime="internal"),
        "memory://",
        "deployment decisions",
        mode="text",
    )

    assert captured["mode"] == "text"
    assert captured["limit"] is None


@pytest.mark.asyncio
async def test_copying_console_text_to_document_collection_creates_document(
    resource_console: TemporaryFileTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.memory as memory

    identifier = uuid4()
    captured: dict[str, object] = {}

    async def create(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"id": str(identifier), "size": 12, "revision": 1}

    monkeypatch.setattr(memory, "create_document_file_resource", create)
    ctx = ResourceContext(agent_id=1, runtime="internal", console_resource=object())
    await resource_service.resource_write_text(
        ctx,
        "console://draft.md",
        "Draft report",
    )

    result = await resource_service.resource_copy(
        ctx,
        "console://draft.md",
        "document://",
    )

    assert result.uri == f"document://{identifier}"
    assert captured["title"] == "draft.md"
    assert captured["content"] == "<p>Draft report</p>"
    assert resource_console.resolve_path(
        "draft.md", create_parent=False
    ).read_text() == "Draft report"


@pytest.mark.asyncio
async def test_messenger_listing_uses_tool_code_room_locator_and_local_file_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    file_id = uuid4()
    attachment = SimpleNamespace(
        id=file_id,
        name="rapport.pdf",
        mime_type="application/pdf",
        size_bytes=42,
    )
    message = SimpleNamespace(
        room=SimpleNamespace(id=room_id, external_id="provider-room"),
        files=[attachment],
    )

    class Messenger:
        async def history(self, room: str, limit: int) -> list[object]:
            assert room == "provider-room"
            assert limit >= 30
            return [message]

    transport = MessengerFileTransport(Messenger())

    async def connected(
        _ctx: ResourceContext,
        _reference: object,
    ) -> tuple[MessengerFileTransport, str, str, str]:
        return transport, "messenger", "placeholder", "provider-room"

    monkeypatch.setattr(resource_service, "_connected_transport", connected)

    result = await resource_service.resource_list(
        ResourceContext(agent_id=1, runtime="internal"),
        "nextcloud://provider-room/",
    )

    assert result.uri == "nextcloud://provider-room/"
    assert [entry.uri for entry in result.entries] == [
        f"nextcloud://provider-room/{file_id}"
    ]
