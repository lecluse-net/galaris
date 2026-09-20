"""
Shared application utilities.
"""

from .yaml import (
    YAMLProcessor,
    YAMLValidationError,
    YAMLProcessingError,
    deep_merge,
    yaml_update,
    load_yaml_file,
    validate_schema,
    load_and_validate,
)
from .encryption import (
    EncryptionService,
    SECRET_MASK,
    encrypt_value,
    decrypt_value,
    encrypt_mapping_values,
    decrypt_mapping_values,
    mask_mapping_values,
    get_encryption_service,
)
from .router_loader import include_routers
from .openapi import generate_filtered_openapi, is_not_internal_path, is_not_internal_tag
from .jsonutil import as_dict, as_list
from .calendar import local_timezone_name, month_bounds
from .transfers import DEFAULT_DOWNLOAD_BYTES, copy_download, read_buffered_file
from .thread_io import complete_await, complete_io
from .http_buffer import post_buffered, read_response
from .byte_budget import BufferedAdmissionDeferred, ByteBudget, buffered_io_budget

from .rich_text import (
    ContentProfile,
    RichTextError,
    attachment_reference,
    archived_document_html,
    convert_to_html,
    convert_legacy_to_html,
    html_blocks,
    image_references,
    normalize_html,
    read_html_page,
    replace_visible_text,
    visible_text,
)
from .editorial_client import require_editorial_client

__all__ = [
    "ContentProfile",
    "RichTextError",
    "attachment_reference",
    "archived_document_html",
    "convert_to_html",
    "convert_legacy_to_html",
    "html_blocks",
    "image_references",
    "normalize_html",
    "read_html_page",
    "replace_visible_text",
    "visible_text",
    "require_editorial_client",
    "complete_io",
    "complete_await",
    "post_buffered",
    "read_response",
    "BufferedAdmissionDeferred",
    "ByteBudget",
    "buffered_io_budget",
    "DEFAULT_DOWNLOAD_BYTES",
    "copy_download",
    "read_buffered_file",
    "YAMLProcessor",
    "YAMLValidationError",
    "YAMLProcessingError",
    "deep_merge",
    "yaml_update",
    "load_yaml_file",
    "validate_schema",
    "load_and_validate",
    "EncryptionService",
    "SECRET_MASK",
    "encrypt_value",
    "decrypt_value",
    "encrypt_mapping_values",
    "decrypt_mapping_values",
    "mask_mapping_values",
    "get_encryption_service",
    "include_routers",
    "generate_filtered_openapi",
    "is_not_internal_path",
    "is_not_internal_tag",
    "as_dict",
    "as_list",
    "local_timezone_name",
    "month_bounds",
]
