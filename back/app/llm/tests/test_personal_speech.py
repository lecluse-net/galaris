from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm import (
    llm_service,
    personal_service,
    profile_service,
    transcription_service,
    tts_service,
)
from app.llm.personal_service import PersonalPreferences, PersonalSpeechError, speech_chunk
from app.llm.profile_models import LlmProfile
from app.llm.models import LLMCall
from app.llm.provider_models import LLM, LLMProvider
from app.llm.provider_facade import SpeechResult, TranscriptionResult
from app.llm.handlers import LLMModelInfo
from core.user import UserModel
from core.util.rich_text import visible_text
from main import app


@pytest_asyncio.fixture
async def selections(db):
    users = [
        UserModel(email=f"speech-{uuid4()}@example.test", hashed_password="unused", is_active=True)
        for _ in range(2)
    ]
    provider = LLMProvider(
        name="Personal voice test",
        provider_type="openai_compatible",
        base_url="https://example.test/v1",
        configuration={},
        is_active=True,
    )
    db.add_all([*users, provider])
    await db.flush()
    models = [
        LLM(
            llm_provider_id=provider.id,
            code=f"speech-{uuid4()}",
            llm_name=f"test-{capability}",
            label=capability,
            resource_type="model",
            primary_capability=capability,
            service_capabilities=[capability],
            pricing={},
        )
        for capability in ("transcription", "speech")
    ]
    db.add_all(models)
    await db.flush()
    profile = LlmProfile(label=f"Personal {uuid4()}", transcription_llm_id=models[0].id)
    empty = LlmProfile(label=f"Empty {uuid4()}")
    db.add_all([profile, empty])
    await db.commit()
    return users, models, profile, empty


@pytest.mark.asyncio
async def test_personal_selection_is_isolated_and_never_mixes_profiles(db, selections, monkeypatch):
    users, models, profile, empty = selections
    monkeypatch.setattr(
        profile_service, "get_current_profile_id", AsyncMock(return_value=profile.id)
    )
    await personal_service.save_preferences(
        users[0].id, PersonalPreferences(profile_id=empty.id, voice_llm_id=models[1].id)
    )
    assert (await personal_service.preferences(users[1].id)) == PersonalPreferences()
    with pytest.raises(PersonalSpeechError, match="transcription_unavailable"):
        await personal_service.transcription_resource(users[0].id)
    assert (await personal_service.transcription_resource(users[1].id)).id == models[0].id
    await personal_service.save_preferences(
        users[0].id, PersonalPreferences(profile_id=profile.id, voice_llm_id=models[1].id)
    )
    with pytest.raises(PersonalSpeechError, match="voice_unavailable"):
        await personal_service.save_preferences(
            users[0].id, PersonalPreferences(voice_llm_id=models[0].id)
        )
    assert (await personal_service.preferences(users[0].id)).voice_llm_id == models[1].id
    await db.delete(profile)
    await db.commit()
    assert (await personal_service.preferences(users[0].id)).profile_id is None
    await llm_service.delete_llm(models[1].id)
    assert (await personal_service.preferences(users[0].id)).voice_llm_id is None


@pytest.mark.asyncio
async def test_speech_uses_personal_voice_and_plain_text_only(db, selections, monkeypatch):
    users, models, profile, _ = selections
    await personal_service.save_preferences(
        users[0].id, PersonalPreferences(profile_id=profile.id, voice_llm_id=models[1].id)
    )
    transport = AsyncMock(return_value=SpeechResult(b"audio", "test", "test"))
    monkeypatch.setattr(tts_service, "_generate_openai_compatible", transport)
    html = (
        '<h1>Titre &amp; voix</h1><p style="text-align:center">Bonjour <strong>tout le monde</strong>.</p>'
        '<p>Autre paragraphe<br>Autre ligne</p><ul><li>Premier élément</li><li>Deuxième élément</li></ul>'
        '<table><tbody><tr><th>Nom</th><th>Valeur</th></tr><tr><td>Exemple</td><td>42</td></tr></tbody></table>'
        '<script>window.secret = 1;</script>'
    )
    audio, offset, done = await personal_service.read_document(users[0].id, html, 0)
    assert audio == b"audio" and done and offset == len(visible_text(html))
    resource, text, _options = transport.call_args.args
    assert resource.id == models[1].id
    assert text == (
        "Titre & voix\nBonjour tout le monde.\nAutre paragraphe\nAutre ligne\n"
        "• Premier élément\n• Deuxième élément\n\nNom\nValeur\n\nExemple\n42"
    )
    with pytest.raises(PersonalSpeechError, match="voice_unavailable"):
        await personal_service.read_document(users[1].id, html, 0)
    assert transport.await_count == 1


@pytest.mark.asyncio
async def test_dictation_resolves_the_human_profile_at_the_provider_boundary(
    db, selections, monkeypatch
):
    users, models, profile, _ = selections
    await personal_service.save_preferences(users[0].id, PersonalPreferences(profile_id=profile.id))
    transport = AsyncMock(return_value=TranscriptionResult(text="Texte dicté"))
    monkeypatch.setattr(transcription_service, "_transcribe_openai_compatible", transport)
    result = await transcription_service.transcribe_audio(
        b"recording", user_id=users[0].id, mime_type="audio/webm"
    )
    assert result == "Texte dicté"
    assert transport.call_args.kwargs["model"] == models[0].llm_name
    recorded = (await db.scalars(select(LLMCall).where(LLMCall.llm_id == models[0].id))).one()
    assert recorded.requester_user_id == users[0].id


def test_long_document_chunks_preserve_all_text_in_order():
    html = (
        "<h1>Rapport</h1><p>"
        + ("Du texte &amp; des mots. " * 1200)
        + "</p><table><tbody><tr><td>Fin</td><td>42</td></tr></tbody></table>"
    )
    chunks, offset, done = [], 0, False
    while not done:
        text, next_offset, done = speech_chunk(html, offset)
        assert len(text) <= 2000 and next_offset > offset
        chunks.append(text)
        offset = next_offset
    assert len(chunks) > 2
    assert "".join(chunks) == visible_text(html).replace("\t", "\n")
    with pytest.raises(PersonalSpeechError, match="empty_document"):
        speech_chunk("<p></p><script>window.test = 1;</script>", 0)


@pytest.mark.asyncio
async def test_http_preferences_and_audio_use_the_authenticated_user_without_document_privileges(
    client, monkeypatch
):
    assert (await client.get("/api/llm/me/preferences")).status_code == 401
    assert (await client.post("/api/llm/me/speech", json={"html": "<p>Test</p>"})).status_code == 401
    assert (
        await client.post(
            "/api/llm/me/transcription",
            files={"file": ("audio.webm", b"audio", "audio/webm")},
        )
    ).status_code == 401
    admin = {"email": f"admin-{uuid4()}@example.com", "password": "strongpassword123"}
    assert (await client.post("/api/auth/register", json=admin)).status_code == 201
    login = await client.post("/api/auth/login-json", json=admin)
    admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    headers = []
    user_ids = []
    for _ in range(2):
        credentials = {"email": f"personal-{uuid4()}@example.com", "password": "strongpassword123"}
        created = await client.post("/api/auth/users", json=credentials, headers=admin_headers)
        assert created.status_code == 201
        user_ids.append(created.json()["id"])
        # Each person owns a browser session. Reusing the admin's cookie jar would
        # intentionally revoke that session when logging in as a different person.
        async with AsyncClient(transport=ASGITransport(app=app), base_url=client.base_url) as browser:
            response = await browser.post("/api/auth/login-json", json=credentials)
        assert response.status_code == 200
        headers.append({"Authorization": f"Bearer {response.json()['access_token']}"})
    options = await client.get("/api/llm/me/options", headers=headers[0])
    assert options.status_code == 200
    profile_id = options.json()["profiles"][0]["id"]
    payload = {
        "profile_id": profile_id,
        "voice_llm_id": None,
        "voice_mode": "tts",
        "voice_code": None,
    }
    assert (
        await client.put("/api/llm/me/preferences", json=payload, headers=headers[0])
    ).status_code == 200
    assert (await client.get("/api/llm/me/preferences", headers=headers[0])).json() == payload
    assert (await client.get("/api/llm/me/preferences", headers=headers[1])).json()[
        "profile_id"
    ] is None
    assert (
        await client.put(
            "/api/llm/me/preferences", json={**payload, "user_id": 1}, headers=headers[0]
        )
    ).status_code == 422
    target_url = f"/api/llm/users/{user_ids[1]}/preferences"
    assert (await client.get(target_url)).status_code == 401
    assert (await client.get(target_url, headers=headers[0])).status_code == 403
    assert (await client.put(target_url, json=payload, headers=headers[0])).status_code == 403
    assert (await client.put(target_url, json=payload, headers=admin_headers)).status_code == 200
    assert (await client.get(target_url, headers=admin_headers)).json() == payload
    assert (await client.get("/api/llm/me/preferences", headers=headers[1])).json() == payload
    assert (
        await client.put(
            "/api/llm/users/2147483647/preferences", json=payload, headers=admin_headers
        )
    ).status_code == 404
    # Personal audio works in any editor, without granting document or LLM administration rights.
    from core.database import get_db_session

    async with get_db_session() as db:
        provider = LLMProvider(
            name="HTTP speech",
            provider_type="openai_compatible",
            base_url="https://example.test/v1",
            configuration={},
            is_active=True,
        )
        db.add(provider)
        await db.flush()
        voice = LLM(
            llm_provider_id=provider.id,
            code=f"http-speech-{uuid4()}",
            llm_name="voice-test",
            label="Voice",
            resource_type="model",
            primary_capability="speech",
            service_capabilities=["speech"],
            pricing={},
        )
        transcription = LLM(
            llm_provider_id=provider.id,
            code=f"http-transcription-{uuid4()}",
            llm_name="transcription-test",
            label="Transcription",
            resource_type="model",
            primary_capability="transcription",
            service_capabilities=["transcription"],
            pricing={},
        )
        db.add_all([voice, transcription])
        await db.flush()
        profile = LlmProfile(label=f"HTTP personal audio {uuid4()}", transcription_llm_id=transcription.id)
        db.add(profile)
        await db.flush()
        voice_id = voice.id
        personal_profile_id = profile.id
        transcription_id = transcription.id
    speech_transport = AsyncMock(return_value=SpeechResult(b"audio", "test", "test"))
    monkeypatch.setattr(tts_service, "_generate_openai_compatible", speech_transport)
    assert (
        await client.put(
            "/api/llm/me/preferences",
            json={"voice_llm_id": voice_id, "profile_id": personal_profile_id},
            headers=headers[0],
        )
    ).status_code == 200
    response = await client.post(
        "/api/llm/me/speech",
        json={"html": "<p>Hello <strong>world</strong>.</p>"},
        headers=headers[0],
    )
    assert response.status_code == 200 and response.content == b"audio"
    assert response.headers["x-speech-done"] == "true"
    assert speech_transport.call_args.args[1] == "Hello world."
    assert (
        await client.post("/api/llm/me/speech", json={"html": "<p>Other account</p>"}, headers=headers[1])
    ).status_code == 400
    assert speech_transport.await_count == 1

    transcription_transport = AsyncMock(return_value=TranscriptionResult(text="Dictated text"))
    monkeypatch.setattr(transcription_service, "_transcribe_openai_compatible", transcription_transport)
    response = await client.post(
        "/api/llm/me/transcription",
        files={"file": ("audio.webm", b"audio", "audio/webm")},
        headers=headers[0],
    )
    assert response.status_code == 200 and response.json() == {"text": "Dictated text"}
    assert transcription_transport.call_args.kwargs["model"] == "transcription-test"
    async with get_db_session() as db:
        call = (await db.scalars(select(LLMCall).where(LLMCall.llm_id == transcription_id))).one()
        assert call.requester_user_id == user_ids[0]


@pytest.mark.asyncio
async def test_native_voice_is_persisted_and_cannot_be_used_as_a_tts_resource(db, selections, monkeypatch):
    users, models, profile, _ = selections
    native = LLM(
        llm_provider_id=models[0].llm_provider_id,
        code=f"native-{uuid4()}",
        llm_name="native",
        label="Native",
        resource_type="model",
        primary_capability="realtime_conversation",
        service_capabilities=["realtime_conversation"],
        pricing={},
    )
    db.add(native)
    await db.commit()
    catalog = AsyncMock(return_value=[LLMModelInfo(id="voice:alloy", name="Alloy", resource_type="voice")])
    monkeypatch.setattr(personal_service.llm_provider_service, "list_resources", catalog)
    options = await personal_service.selection_options()
    assert [(option.model_id, option.voice_code) for option in options.native_voices] == [(native.id, "voice:alloy")]
    catalog.side_effect = RuntimeError("Provider catalog unavailable")
    degraded = await personal_service.selection_options()
    assert degraded.native_voices_error and not degraded.native_voices
    assert models[1].id in {voice.id for voice in degraded.voices}
    assert profile.id in {option.id for option in degraded.profiles}
    choice = PersonalPreferences(
        profile_id=profile.id,
        voice_llm_id=native.id,
        voice_mode="realtime",
        voice_code="voice:alloy",
    )
    assert await personal_service.save_preferences(users[0].id, choice) == choice
    assert await personal_service.preferences(users[0].id) == choice
    with pytest.raises(PersonalSpeechError, match="voice_unavailable"):
        await personal_service.read_document(users[0].id, "<p>Text</p>", 0)
    with pytest.raises(PersonalSpeechError, match="voice_unavailable"):
        await personal_service.save_preferences(
            users[0].id, PersonalPreferences(voice_llm_id=native.id)
        )
    with pytest.raises(ValueError):
        PersonalPreferences(voice_mode="realtime", voice_llm_id=native.id)
    await llm_service.delete_llm(native.id)
    assert await personal_service.preferences(users[0].id) == PersonalPreferences(
        profile_id=profile.id
    )
