"""
AFFiNE file bridge for blob upload and download.

This pure client is used by ``app.file_share`` and has no router or model, so it
is not listed in ``back/modules.py``.
"""

from .client import AffineFileClient

__all__ = ["AffineFileClient"]
