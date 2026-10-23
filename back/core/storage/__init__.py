"""Shared file identities and disk storage; access belongs to referring domains."""

from .disk import DiskFileDriver, FileDriver, file_key, file_path, fingerprint, sync_directory
from .models import FileAlias, StoredFile
from .registry import register_file
from .names import FileRename, validate_file_name, registered_file_names, rename_stored_file
from .identity import ensure_disk_identity
from .lifecycle import discard_unregistered_file, purge_retired_file, retire_file_references, retire_file_reference

__all__ = [
    "FileRename", "validate_file_name", "registered_file_names", "rename_stored_file",
    "DiskFileDriver", "FileDriver", "FileAlias", "StoredFile", "file_key", "file_path",
    "fingerprint", "register_file", "sync_directory", "ensure_disk_identity",
    "purge_retired_file", "retire_file_references",
    "retire_file_reference",
    "discard_unregistered_file",
    "ResourceStorage", "ResourceStorageError", "ResourceNotFoundError", "ResourceTooLargeError",
    "NativeFileStorage", "AttachmentFileStorage", "get_storage", "get_attachment_storage",
    "register_storage", "registered_storage_codes", "reset_storage_registry",
    "prepare_content", "register_resource_content", "resource_is_referenced",
]

from .resource_contracts import ResourceStorage, ResourceStorageError, ResourceNotFoundError, ResourceTooLargeError
from .resources import NativeFileStorage, AttachmentFileStorage, get_storage, get_attachment_storage, register_storage, registered_storage_codes, reset_storage_registry
from .resource_content import prepare_content, register_resource_content, resource_is_referenced, referenced_resources
__all__.append("referenced_resources")
