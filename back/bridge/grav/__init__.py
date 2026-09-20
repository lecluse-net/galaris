"""
Grav file bridge for media upload and download.

This pure client is used by ``app.file_share`` and has no router or model, so it
is not listed in ``back/modules.py``.
"""

from .client import GravFileClient

__all__ = ["GravFileClient"]
