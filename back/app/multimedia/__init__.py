"""Specialist sound, music and video tools. Voice/STT remains independent."""

from sqlalchemy import select
from app.process import registry, register_retention_guard
from .engine import MultimediaEngine
from .models import MediaOutputReceipt

registry.register(MultimediaEngine())
register_retention_guard("multimedia.receipts", lambda: select(MediaOutputReceipt.run_id).where(
    MediaOutputReceipt.content.is_not(None),
))

__all__ = ["MediaOutputReceipt"]
