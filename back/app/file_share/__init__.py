"""Streaming file transfer across canonical providers and external services.

Every service implements the same ``FileTransport`` protocol. Streaming-capable pairs transfer
directly with bounded memory; legacy transports retain a temporary-file fallback. External
services are registered bridges and Messenger attachments keep their provider identity.
"""

from . import file_share_service
from .models import FileCatalogEntry, FileIndexRun, FileObservationRepair
from .indexing import indexing_tick, repair_tick, start_index_run, cancel_index_run, prune_index_history, refresh_known_tick
from .catalogue import annotate_catalogue_entry, catalogue_access_clause, catalogue_source_readable, catalogue_sources_readable
from .resource_observation import observe_received_resources as observe_received_resources
from app.memory import register_source_access, register_url_reference_merger
from .catalogue import merge_catalogue_url_references

register_url_reference_merger("file_catalogue", merge_catalogue_url_references)

register_source_access("file_catalogue", catalogue_access_clause, catalogue_source_readable,
                       batch_reader=catalogue_sources_readable)
from .bridges import (
    FileShareBridge,
    FileShareBridgeInfo,
    FileShareParamInfo,
    available_bridges,
    register,
)
from .messenger_transport import MessengerFileTransport
from .path_normalization import (
    FilePathError,
    join_file_references,
    normalize_transport_reference,
    normalize_file_reference,
)
from .transport import (
    FileTransport,
    ShareableFileTransport,
    StreamingFileTransport,
    transfer,
)
from .resource_contracts import (
    DeliveredResource,
    MaterializedResource,
    ResourceCapability,
    ResourceContext,
    ResourceDescriptor,
    ResourceListing,
    ResourceMutation,
    ResourceSchemeDescription,
    ResourceSearchHit,
    ResourceSearchResult,
    ResourceRead,
    ResourceTransfer,
)
from .resource_delivery import deliver_resource_to_messenger
from .resource_description import record_resource_description
from .resource_service import (
    list_schemes,
    materialize_resource,
    preferred_local_resource_uri,
    resource_accessible,
    resource_append,
    resource_copy,
    resource_create,
    resource_delete,
    resource_info,
    resource_list,
    resource_move,
    resource_read,
    resource_edit,
    resource_search,
    resource_write,
)
from .resource_uri import (
    NATIVE_RESOURCE_SCHEMES,
    PROTOCOL_SCHEMES,
    FUTURE_RESOURCE_SCHEMES,
    RESERVED_TOOL_CODES,
    SYSTEM_TOOL_CODES,
    ResourceUri,
    ResourceUriError,
    ResourceRevisionConflict,
    ResourceValidationError,
    parse_resource_uri,
    validate_external_tool_code,
)
from .file_contracts import (
    FileResourceTransport,
    FileEntry,
    FileListing,
    FileMutation,
    FileText,
)
from .web_transport import PublicHttpsContent, read_public_https_bytes

__all__ = [
    "FileCatalogEntry", "annotate_catalogue_entry",
    "record_resource_description",
    "WebMetadata", "web_metadata",
    "file_share_service",
    "available_bridges",
    "register",
    "FileShareBridge",
    "FileShareBridgeInfo",
    "FileShareParamInfo",
    "FileTransport",
    "ShareableFileTransport",
    "StreamingFileTransport",
    "MessengerFileTransport",
    "FilePathError",
    "join_file_references",
    "normalize_transport_reference",
    "normalize_file_reference",
    "transfer",
    "NATIVE_RESOURCE_SCHEMES",
    "PROTOCOL_SCHEMES",
    "FUTURE_RESOURCE_SCHEMES",
    "RESERVED_TOOL_CODES",
    "SYSTEM_TOOL_CODES",
    "ResourceCapability",
    "DeliveredResource",
    "MaterializedResource",
    "ResourceContext",
    "resource_accessible",
    "ResourceDescriptor",
    "ResourceListing",
    "ResourceMutation",
    "ResourceSchemeDescription",
    "ResourceSearchHit",
    "ResourceSearchResult",
    "ResourceRead",
    "ResourceTransfer",
    "ResourceUri",
    "ResourceUriError",
    "ResourceRevisionConflict",
    "ResourceValidationError",
    "FileResourceTransport",
    "FileEntry",
    "FileListing",
    "FileMutation",
    "FileText",
    "PublicHttpsContent",
    "read_public_https_bytes",
    "list_schemes",
    "materialize_resource",
    "deliver_resource_to_messenger",
    "preferred_local_resource_uri",
    "parse_resource_uri",
    "resource_append",
    "resource_copy",
    "resource_create",
    "resource_delete",
    "resource_info",
    "resource_list",
    "resource_move",
    "resource_read",
    "resource_edit",
    "resource_search",
    "resource_write",
    "validate_external_tool_code",
]

from .web_preview import WebMetadata, web_metadata

from .web_preview import document_web_preview as document_web_preview
from .web_preview import document_web_image
from .document_facade import prepared_resource
__all__ += ["prepared_resource"]
from core.preview import register_web_image_provider

register_web_image_provider(document_web_image)

from .planner_adapter import register_planner_inventory_adapter

register_planner_inventory_adapter()
__all__ += ["FileIndexRun", "FileObservationRepair", "indexing_tick", "repair_tick", "start_index_run", "cancel_index_run", "prune_index_history", "refresh_known_tick"]

from .enrichment import descriptor_version, pending_enrichments, apply_enrichment, FileCatalogueEnrichmentPort
__all__ += ["descriptor_version", "pending_enrichments", "apply_enrichment", "FileCatalogueEnrichmentPort"]
