"""Unified API entry point for the LLM module."""

from fastapi import APIRouter

from .anthropic_router import router as anthropic_router
from .call_router import router as call_router
from .profile_router import router as profile_router
from .profile_inference_router import router as profile_inference_router
from .provider_router import router as provider_router
from .personal_router import router as personal_router
from .personal_router import user_router as user_preferences_router


router = APIRouter()
router.include_router(personal_router)
router.include_router(user_preferences_router)
router.include_router(provider_router)
router.include_router(profile_router)
router.include_router(profile_inference_router)
router.include_router(call_router)
router.include_router(anthropic_router)
