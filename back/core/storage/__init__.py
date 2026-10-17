"""Shared file identities and disk storage; access belongs to referring domains."""

from .disk import DiskFileDriver, FileDriver, file_key, file_path, fingerprint, sync_directory
from .models import FileAlias, StoredFile
from .registry import register_file
from .identity import ensure_disk_identity
from .lifecycle import discard_unregistered_file, purge_retired_file, retire_file_references, retire_file_reference

__all__ = [
    "DiskFileDriver", "FileDriver", "FileAlias", "StoredFile", "file_key", "file_path",
    "fingerprint", "register_file", "sync_directory", "ensure_disk_identity",
    "purge_retired_file", "retire_file_references",
    "retire_file_reference",
    "discard_unregistered_file",
]
