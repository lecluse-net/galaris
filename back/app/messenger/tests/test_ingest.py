from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.llm import llm_service, transcription_service
from app.messenger import facade, ingest, session
from app.messenger.models import AUDIO_TRANSCRIPT_METADATA_KEY, File, Message


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['bridge_write', 'pdf_write', 'office_write', 'pdf_read'])
async def test_attachment_disk_io_leaves_other_requests_running(tmp_path, monkeypatch, stage):
    import asyncio
    from pathlib import Path
    from threading import Event
    from zipfile import ZipFile
    from app.messenger.interface import Messenger
    from app.messenger._observations import ObservedMessengerFile
    from tests.test_document_pipeline import pdf

    source = tmp_path / ('synthetic.odt' if stage == 'office_write' else 'synthetic.pdf')
    if stage == 'office_write':
        with ZipFile(source, 'w') as archive:
            archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
            archive.writestr('META-INF/manifest.xml', '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
            archive.writestr('content.xml', '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:text><text:p>Synthetic evidence 1200.</text:p></office:text></office:body></office:document-content>')
    else:
        pdf(source)
    data = source.read_bytes()
    monkeypatch.setattr(ingest, 'fetch_bytes', AsyncMock(return_value=data))
    messenger = SimpleNamespace(fetch_attachment=AsyncMock(return_value=data))
    attachment = File(id=uuid4(), name=source.name, mime_type='application/pdf' if source.suffix == '.pdf' else 'application/vnd.oasis.opendocument.text', kind='document')
    entered, released = Event(), Event()
    original_write, original_read = Path.write_bytes, Path.read_bytes
    destination = tmp_path / 'copied.pdf'

    def wait_for_other_request():
        entered.set()
        assert released.wait(3), 'Attachment filesystem I/O blocked unrelated asynchronous work'

    def write_bytes(path, content):
        if (stage == 'bridge_write' and path == destination) or (
            stage in {'pdf_write', 'office_write'} and path.name == 'input'
        ):
            wait_for_other_request()
        return original_write(path, content)

    def read_bytes(path):
        if stage == 'pdf_read' and path.suffix == '.png':
            wait_for_other_request()
        return original_read(path)

    monkeypatch.setattr(Path, 'write_bytes', write_bytes)
    monkeypatch.setattr(Path, 'read_bytes', read_bytes)

    async def unrelated_request():
        while not entered.is_set():
            await asyncio.sleep(0.001)
        released.set()

    async with asyncio.TaskGroup() as group:
        other = group.create_task(unrelated_request())
        try:
            if stage == 'bridge_write':
                count = await Messenger.fetch_attachment_to_file(messenger, ObservedMessengerFile(), destination)
                assert count == len(data) and original_read(destination) == data
            elif stage == 'pdf_read':
                images = await ingest.pdf_to_images(messenger, attachment)
                assert len(images) == 1 and images[0][1] == 'image/png'
                assert images[0][0].startswith(b'\x89PNG')
            else:
                assert '1200' in await ingest._extract(messenger, attachment, 'en')
        finally:
            if not entered.is_set():
                other.cancel()
    assert entered.is_set(), 'The source I/O stage must be exercised'


@pytest.mark.asyncio
async def test_attachment_inline_limit_changes_without_reload(monkeypatch):
    from core.params import runtime_settings

    attachment = File(id=uuid4(), connection_id=7, external_identifier='provider-file', name='image.png', mime_type='image/png', size_bytes=2 * 1024 * 1024, kind='image')
    messenger = SimpleNamespace(tool_id=3)
    fetch = AsyncMock(return_value=b'image-content')
    monkeypatch.setattr(ingest, 'fetch_bytes', fetch)
    for limit, accepted in [(1, False), (2, True), (2_000_000 / 1_048_576, False), (1, False)]:
        fetch.reset_mock()
        monkeypatch.setattr(runtime_settings, 'MESSENGER_MAX_INLINE_MB', limit)
        content = await ingest.as_openai_content(messenger, [attachment], 'Message', SimpleNamespace(image=True), language='en')
        assert isinstance(content, list) is accepted
        if accepted:
            fetch.assert_awaited_once()
            assert any(part.get('type') == 'image_url' for part in content)
        else:
            fetch.assert_not_awaited()
            assert 'image.png' in content


def _audio_message() -> tuple[Message, File]:
    audio = File(
        id=uuid4(),
        connection_id=7,
        external_identifier="voice-provider-id",
        name="note-vocale.ogg",
        mime_type="audio/ogg",
        size_bytes=42,
        kind="audio",
    )
    message = Message(
        id=uuid4(),
        connection_id=7,
        tool_id=3,
        platform="internal",
        remote_message_id="audio-message",
        direction="inbound",
        text="Contexte écrit",
        attachments=[],
        metadata_={},
        created_at=datetime.now(timezone.utc),
    )
    message.files = [audio]
    return message, audio


@pytest.mark.asyncio
@pytest.mark.parametrize("input_audio", [False, True])
async def test_audio_is_transcribed_when_model_or_transport_cannot_accept_it(
    monkeypatch: pytest.MonkeyPatch,
    input_audio: bool,
) -> None:
    message, audio = _audio_message()
    messenger = SimpleNamespace(connection_id=7)
    database = SimpleNamespace(
        get=AsyncMock(return_value=message),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        llm_service,
        "get_profile_llm_for_agent_id",
        AsyncMock(return_value=SimpleNamespace(input_audio=input_audio)),
    )
    monkeypatch.setattr(
        transcription_service,
        "transcription_available_for_agent",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(facade, "get_messenger", AsyncMock(return_value=messenger))
    transcribe = AsyncMock(return_value="Bonjour depuis la note vocale.")
    monkeypatch.setattr(ingest, "_transcribe", transcribe)
    monkeypatch.setattr(ingest, "get_db", lambda: database)

    assert await ingest.transcribe_audio_for_conversation(message, agent_id=11)

    transcribe.assert_awaited_once_with(messenger, audio, agent_id=11)
    assert message.metadata_[AUDIO_TRANSCRIPT_METADATA_KEY] == {
        str(audio.id): "Bonjour depuis la note vocale."
    }
    database.commit.assert_awaited_once_with()
    assert message.conversation_text == (
        "Contexte écrit\n\n"
        "[Audio transcript: note-vocale.ogg]\n"
        "Bonjour depuis la note vocale."
    )
    projected = session._record_message(  # pyright: ignore[reportPrivateUsage]
        message,
        agent_id=11,
        tool_code="chat",
    )
    assert projected["text"] == message.conversation_text


@pytest.mark.asyncio
async def test_audio_capable_conversation_model_bypasses_stt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message, _audio = _audio_message()
    _audio.mime_type = "audio/wav"
    _audio.name = "sample.wav"
    monkeypatch.setattr(
        llm_service,
        "get_profile_llm_for_agent_id",
        AsyncMock(return_value=SimpleNamespace(input_audio=True)),
    )
    available = AsyncMock(return_value=True)
    monkeypatch.setattr(
        transcription_service,
        "transcription_available_for_agent",
        available,
    )
    transcribe = AsyncMock(return_value="should not be used")
    monkeypatch.setattr(ingest, "_transcribe", transcribe)

    assert not await ingest.transcribe_audio_for_conversation(message, agent_id=11)

    available.assert_not_awaited()
    transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_stt_keeps_audio_message_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message, _audio = _audio_message()
    monkeypatch.setattr(
        llm_service,
        "get_profile_llm_for_agent_id",
        AsyncMock(return_value=SimpleNamespace(input_audio=False)),
    )
    monkeypatch.setattr(
        transcription_service,
        "transcription_available_for_agent",
        AsyncMock(return_value=False),
    )
    transcribe = AsyncMock(return_value="should not be used")
    monkeypatch.setattr(ingest, "_transcribe", transcribe)

    assert not await ingest.transcribe_audio_for_conversation(message, agent_id=11)

    assert message.conversation_text == "Contexte écrit"
    transcribe.assert_not_awaited()
