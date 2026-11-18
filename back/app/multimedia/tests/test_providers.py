import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.llm import MediaRequest, MusicComposition
from app.llm.facade import MediaProviderUnavailable, MediaRequestRejected
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


@pytest.mark.asyncio
async def test_suno_distinguishes_ambiguous_admission_from_explicit_rejection(monkeypatch):
    from bridge.sunoapi import media

    transport = AsyncMock(side_effect=[{"code": 503}, {"code": 402}, {"code": 455}])
    monkeypatch.setattr(media, "media_json", transport)
    provider, account = SunoApiMedia(), connection("sunoapi")
    request = MediaRequest(operation="music_generate", model="V5", prompt="Piano")
    with pytest.raises(MediaProviderUnavailable):
        await provider.submit(account, request, callback_url="https://galaris.test/callback")
    with pytest.raises(MediaRequestRejected, match="402"):
        await provider.submit(account, request, callback_url="https://galaris.test/callback")
    with pytest.raises(MediaProviderUnavailable):
        await provider.poll(account, request, "accepted-job")


def test_provider_limits_are_checked_before_admission():
    with pytest.raises(ValueError, match="duration"):
        SunoApiMedia().validate(MediaRequest(operation="music_generate", model="V5", prompt="Music", duration=30))
    with pytest.raises(ValueError, match="30 seconds"):
        ElevenLabsMedia().validate(MediaRequest(operation="sound_generate", model="eleven_text_to_sound_v2", prompt="Waves", duration=40))
    assert not ElevenLabsMedia().supports("audio_read", "scribe_v2")
    assert not ElevenLabsMedia().supports("music_generate", "voice:123")
    with pytest.raises(ValueError, match="resolution"):
        BytePlusMedia().validate(MediaRequest(operation="video_generate", model="dreamina-seedance-2-0-fast-260128",
                                              prompt="Blue sky", resolution="1080p"))


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
@pytest.mark.parametrize("model", ["music_v1", "music_v2", "music_v2_5"])
async def test_eleven_music_composition_preserves_sections_and_verbatim_lyrics(monkeypatch, model):
    from bridge.elevenlabs import multimedia

    transport = AsyncMock(return_value=b"ID3synthetic")
    monkeypatch.setattr(multimedia, "media_http", transport)
    plan = MusicComposition.model_validate({"styles": ["acoustic"], "sections": [
        {"name": "Intro", "duration_ms": 4500, "styles": ["piano"]},
        {"name": "Verse", "duration_ms": 7000, "lyrics": ["La pluie s’arrête.", "Le ciel s’ouvre."]},
    ]})
    request = MediaRequest(operation="music_generate", model=model, prompt="Jazz", composition=plan)
    await ElevenLabsMedia().submit(connection("elevenlabs"), request, callback_url="")
    body = transport.await_args.kwargs["body"]
    assert "prompt" not in body and "music_length_ms" not in body
    if model == "music_v1":
        assert body["composition_plan"]["positive_global_styles"] == ["Jazz", "acoustic"]
        assert body["composition_plan"]["sections"][1]["lines"] == ["La pluie s’arrête.", "Le ciel s’ouvre."]
        assert [section["duration_ms"] for section in body["composition_plan"]["sections"]] == [4500, 7000]
    else:
        chunks = body["composition_plan"]["chunks"]
        assert chunks[0]["positive_styles"] == ["Jazz", "acoustic", "piano"]
        assert chunks[1]["text"] == "[Verse]\nLa pluie s’arrête.\nLe ciel s’ouvre."
        assert [chunk["duration_ms"] for chunk in chunks] == [4500, 7000]

    with pytest.raises(ValueError, match="Do not combine"):
        ElevenLabsMedia().validate(request.model_copy(update={"duration": 30}))
    with pytest.raises(ValueError, match="structured music composition"):
        OpenRouterMedia().validate(request.model_copy(update={"model": "google/lyria-3-pro-preview"}))


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
@pytest.mark.parametrize("status", ["succeeded", "cancelled"])
async def test_seedance_checks_status_before_returning_a_file(monkeypatch, status):
    from bridge.byteplus import media
    transport = AsyncMock(side_effect=[{"id": "video-1"}, {"status": "running"},
        {"status": status, "content": {"video_url": "https://cdn.test/video.mp4"}}])
    monkeypatch.setattr(media, "media_json", transport)
    provider = BytePlusMedia()
    request = MediaRequest(operation="video_generate", model="dreamina-seedance-2-0-260128", prompt="Ocean", duration=5)
    result = await provider.submit(connection("byteplus"), request, callback_url="")
    assert result.external_id == "video-1"
    assert (await provider.poll(connection("byteplus"), request, result.external_id)).state == "running"
    final = await provider.poll(connection("byteplus"), request, result.external_id)
    if status == "cancelled":
        assert final.state == "cancelled" and not final.artifacts
    else:
        assert final.state == "success" and final.artifacts[0].url.endswith("video.mp4")


@pytest.mark.asyncio
async def test_openrouter_catalog_failure_is_confirmed_to_precede_video_submission(monkeypatch):
    from bridge.openrouter import multimedia

    transport = AsyncMock(side_effect=MediaProviderUnavailable("catalog unavailable"))
    monkeypatch.setattr(multimedia, "media_json", transport)
    request = MediaRequest(operation="video_generate", model="synthetic/model", prompt="Ocean")
    with pytest.raises(MediaRequestRejected, match="No generation was submitted"):
        await OpenRouterMedia().submit(connection("openrouter"), request, callback_url="")
    assert [call.args[1:] for call in transport.await_args_list] == [("GET", "videos/models")]
