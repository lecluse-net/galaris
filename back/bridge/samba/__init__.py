"""SMB 2/3 shares exposed through the canonical file-share facade."""

from app.file_share import register
from .file_share import SAMBA_FILE_SHARE_BRIDGE, SambaFileClient

register(SAMBA_FILE_SHARE_BRIDGE)

__all__ = ["SAMBA_FILE_SHARE_BRIDGE", "SambaFileClient"]
