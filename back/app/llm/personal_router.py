"""Authenticated self-service preferences and bounded document audio operations."""

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from core.authorize import Privileges, authorize
from core.i18n import tr
from core.user import get_current_user_id, get_user_record

from . import personal_service, transcription_service
from .personal_service import PersonalOptions, PersonalPreferences, PersonalSpeechError

router = APIRouter(prefix="/llm/me", tags=["personal-llm"])
user_router = APIRouter(prefix="/llm/users", tags=["user-llm"])
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class SpeechRequest(BaseModel):
    html: str = Field(max_length=2_000_000)
    offset: int = Field(default=0, ge=0)


class TranscriptionResponse(BaseModel):
    text: str


def _user_id() -> int:
    user_id = get_current_user_id()
    if user_id is None:
        raise HTTPException(status_code=401)
    return user_id


async def _error(code: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=await tr(f"personal_speech.{code}"))


@router.get("/preferences")
@authorize()
async def get_preferences() -> PersonalPreferences:
    return await personal_service.preferences(_user_id())


@router.put("/preferences")
@authorize()
async def put_preferences(values: PersonalPreferences) -> PersonalPreferences:
    try:
        return await personal_service.save_preferences(_user_id(), values)
    except PersonalSpeechError as exc:
        raise await _error(str(exc)) from exc


@router.get("/options")
@authorize()
async def get_options() -> PersonalOptions:
    _user_id()
    return await personal_service.selection_options()


async def _require_user(user_id: int) -> None:
    if await get_user_record(user_id) is None:
        raise await _error("user_unavailable", 404)


@user_router.get("/{user_id}/preferences")
@authorize(privileges=[Privileges.READ_USER, Privileges.UPDATE_USER])
async def get_user_preferences(user_id: int) -> PersonalPreferences:
    await _require_user(user_id)
    return await personal_service.preferences(user_id)


@user_router.put("/{user_id}/preferences")
@authorize(privileges=Privileges.UPDATE_USER)
async def put_user_preferences(user_id: int, values: PersonalPreferences) -> PersonalPreferences:
    await _require_user(user_id)
    try:
        return await personal_service.save_preferences(user_id, values)
    except PersonalSpeechError as exc:
        raise await _error(str(exc)) from exc


@router.post("/transcription")
@authorize()
async def transcribe(
    file: UploadFile = File(...), language: str = Form(default="", max_length=20)
) -> TranscriptionResponse:
    user_id = _user_id()
    try:
        content = await file.read(MAX_AUDIO_BYTES + 1)
        if len(content) > MAX_AUDIO_BYTES:
            raise await _error("audio_too_large", 413)
        mime = (file.content_type or "").split(";", 1)[0].strip().lower()
        if not content or mime not in {
            "audio/webm",
            "audio/mp4",
            "audio/mpeg",
            "audio/ogg",
            "audio/wav",
            "audio/x-wav",
            "audio/flac",
        }:
            raise await _error("invalid_audio")
        text = await transcription_service.transcribe_audio(
            content,
            filename="dictation." + transcription_service.audio_format(mime),
            mime_type=mime,
            language=language,
            user_id=user_id,
        )
        return TranscriptionResponse(text=text)
    except PersonalSpeechError as exc:
        raise await _error(str(exc)) from exc
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise await _error("provider_failed", 502) from exc
    finally:
        await file.close()


@router.post("/speech")
@authorize()
async def speech(payload: SpeechRequest) -> Response:
    try:
        audio, offset, done = await personal_service.read_document(
            _user_id(), payload.html, payload.offset
        )
    except PersonalSpeechError as exc:
        raise await _error(str(exc)) from exc
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise await _error("provider_failed", 502) from exc
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Next-Offset": str(offset),
            "X-Speech-Done": str(done).lower(),
        },
    )
