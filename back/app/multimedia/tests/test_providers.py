import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.llm import MediaRequest
from app.llm.provider_facade import ProviderConnection
from bridge.byteplus.media import BytePlusMedia
from bridge.elevenlabs.multimedia import ElevenLabsMedia
from bridge.openrouter.multimedia import OpenRouterMedia
from bridge.sunoapi.media import SunoApiMedia


def connection(code):
    return ProviderConnection(id=1, name=code, catalog_code=code, provider_type=code,
                              base_url="https://provider.test/v1", api_key="secret")


@pytest.mark.asyncio
async def test_suno_submission_and_two_track_completion(monkeypatch):
    from bridge.sunoapi import media
    transport = AsyncMock(side_effect=[
        {"code": 200, "data": {"taskId": "job-1"}},
        {"code": 200, "data": {"status": "SUCCESS", "response": {"sunoData": [
            {"id": "a", "audioUrl": "https://cdn.test/a.mp3"},
            {"id": "b", "audio_url": "https://cdn.test/b.mp3"},
        ]}}},
    ])
    monkeypatch.setattr(media, "media_json", transport)
    request = MediaRequest(operation="music_generate", model="V5_5", prompt="Piano", lyrics="Hello",
                           style="Jazz", title="Song", duration=60)
    provider = SunoApiMedia()
    first = await provider.submit(connection("sunoapi"), request, callback_url="https://galaris.test/callback")
    assert first.external_id == "job-1"
    body = transport.await_args.kwargs["body"]
    assert body["prompt"] == "Hello"
    assert body["customMode"] is True
    assert body["duration"] == 60
    result = await provider.poll(connection("sunoapi"), request, first.external_id)
    assert result.state == "success"
    assert [item.external_id for item in result.artifacts] == ["a", "b"]
    assert result.cost is None


def test_provider_limits_are_checked_before_admission():
    with pytest.raises(ValueError, match="duration"):
        SunoApiMedia().validate(MediaRequest(operation="music_generate", model="V5", prompt="Music", duration=30))
    with pytest.raises(ValueError, match="30 seconds"):
        ElevenLabsMedia().validate(MediaRequest(operation="sound_generate", model="eleven_text_to_sound_v2", prompt="Waves", duration=40))
    assert not ElevenLabsMedia().supports("audio_read", "scribe_v2")
    assert not ElevenLabsMedia().supports("music_generate", "voice:123")


@pytest.mark.asyncio
async def test_eleven_music_and_sounds_use_separate_endpoints(monkeypatch):
    from bridge.elevenlabs import multimedia
    transport = AsyncMock(return_value=b"ID3audio")
    monkeypatch.setattr(multimedia, "media_http", transport)
    provider = ElevenLabsMedia()
    await provider.submit(connection("elevenlabs"), MediaRequest(operation="music_generate", model="music_v1", prompt="Jazz",
                           duration=20, instrumental=True), callback_url="")
    assert transport.await_args.args[2] == "music"
    assert transport.await_args.kwargs["body"]["music_length_ms"] == 20000
    assert transport.await_args.kwargs["body"]["force_instrumental"] is True
    await provider.submit(connection("elevenlabs"), MediaRequest(operation="sound_generate", model="eleven_text_to_sound_v2",
                           prompt="Waves", loop=True), callback_url="")
    assert transport.await_args.args[2] == "sound-generation"
    assert transport.await_args.kwargs["auth_header"] == "xi-api-key"


@pytest.mark.asyncio
async def test_openrouter_audio_uses_encoded_content_not_a_url(monkeypatch, tmp_path: Path):
    from bridge.openrouter import multimedia
    transport = AsyncMock(return_value={"choices": [{"message": {"content": "Bird calls"}}], "usage": {"cost": 0.01}})
    monkeypatch.setattr(multimedia, "media_json", transport)
    path = tmp_path / "song.wav"
    path.write_bytes(b"RIFFaudio")
    result = await OpenRouterMedia().analyze(connection("openrouter"),
        MediaRequest(operation="audio_read", model="google/gemini", prompt="Identify sounds"), path, "audio/wav")
    assert result.text == "Bird calls"
    part = transport.await_args.kwargs["body"]["messages"][0]["content"][1]
    assert part == {"type": "input_audio", "input_audio": {"format": "wav", "data": base64.b64encode(b"RIFFaudio").decode()}}


@pytest.mark.asyncio
async def test_lyria_reassembles_arbitrary_base64_boundaries_and_requires_completion(monkeypatch):
    from bridge.openrouter import multimedia
    encoded = base64.b64encode(b"RIFFmusic").decode()
    chunks = [encoded[:3], encoded[3:7], encoded[7:]]
    lines = ["data: " + json.dumps({"choices": [{"delta": {"audio": {"data": chunk}}}]}) for chunk in chunks]
    transport = AsyncMock(return_value=("\n\n".join(lines) + "\n\ndata: [DONE]\n").encode())
    monkeypatch.setattr(multimedia, "media_http", transport)
    request = MediaRequest(operation="music_generate", model="google/lyria-3-pro-preview", prompt="Jazz")
    provider = OpenRouterMedia()
    result = await provider.submit(connection("openrouter"), request, callback_url="")
    assert result.artifacts[0].content == b"RIFFmusic"
    assert result.artifacts[0].media_type == "audio/wav"
    transport.return_value = "\n\n".join(lines).encode()
    with pytest.raises(ValueError, match="complete"):
        await provider.submit(connection("openrouter"), request, callback_url="")


@pytest.mark.asyncio
async def test_seedance_checks_status_before_returning_a_file(monkeypatch):
    from bridge.byteplus import media
    transport = AsyncMock(side_effect=[{"id": "video-1"}, {"status": "running"},
        {"status": "succeeded", "content": {"video_url": "https://cdn.test/video.mp4"}}])
    monkeypatch.setattr(media, "media_json", transport)
    provider = BytePlusMedia()
    request = MediaRequest(operation="video_generate", model="dreamina-seedance-2-0-260128", prompt="Ocean", duration=5)
    result = await provider.submit(connection("byteplus"), request, callback_url="")
    assert result.external_id == "video-1"
    assert (await provider.poll(connection("byteplus"), request, result.external_id)).state == "running"
    assert (await provider.poll(connection("byteplus"), request, result.external_id)).artifacts[0].url.endswith("video.mp4")
