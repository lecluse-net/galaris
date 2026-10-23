"""Governed, durable memory public surface."""

from .temporal import MemoryTemporalAnchor
from .document_app_security import AppConsentRequired, AppWriteLimitError
from .dataset_port import register_dataset_compatibility, refresh_dataset_projection, legacy_dataset_access, budget_reserved as dataset_budget_reserved
from .dataset_migration import legacy_dataset_ids, legacy_dataset_snapshot, legacy_dataset_exists
from .process_migration import legacy_process_snapshot as legacy_process_snapshot, retire_legacy_process_document as retire_legacy_process_document
from .dataset_references import list_selectable_documents
from .dataset_attachments import DatasetAttachmentReference, register_dataset_attachment_reader
from .document_attachment_service import validate_attachment_content
from .document_attachment_service import rename_document_attachment
from .document_types import register_document_validator
from .schemas import DocumentCollaborator, DocumentSharing, DocumentSharingLevelUpdate
from .item_sharing import sharing_directory as resource_sharing_directory
from .dataset_usage import find_dataset_document_usages
from .workflow_documents import (
    create_workflow_document, read_workflow_document, write_workflow_document,
    workflow_document_actor, workflow_document_access, workflow_document_readable_ids, prepare_workflow_document_read,
    workflow_history, workflow_revision, restore_workflow_document, delete_workflow_revision, workflow_sharing, workflow_sharing_preview, update_workflow_sharing,
    share_workflow_document,
    workflow_document_is_orphan,
    workflow_document_policy_ids,
    workflow_document_titles,
)
from .catalogue_projection import project_catalogue_entry, link_catalogue_entries, catalogue_projection_write, detach_catalogue_parent_links
from .catalogue_projection import identify_catalogue_file as identify_catalogue_file, update_catalogue_file_locations as update_catalogue_file_locations, catalogue_file_summary as catalogue_file_summary
from .document_thumbnail_service import render_file_thumbnail as render_file_thumbnail
from .document_thumbnail_service import generate_document_attachment_thumbnail as generate_document_attachment_thumbnail
from .document_thumbnail_service import read_document_thumbnail as read_document_thumbnail
from .schemas import DocumentThumbnailRender as DocumentThumbnailRender
from .models import DocumentAttachment as DocumentAttachment
from .source_access import register_source_access

from .contracts import (
    ContactReferenceCleaner,
    ContactReferenceRewriter,
    MemoryAccess,
    MemoryBrief,
    MemoryContextItem,
    MemorySearchItem,
    MemoryUsageObservation,
    MessengerContactObservation,
    MessengerContactIdentity,
    MessengerContactIdentityInput,
    MessengerContactRecord,
    ResourceStorage,
    TaskMemoryAssociationResult,
    TopicLinkedMemory,
    TopicLinkedDocument,
    TopicProjectionMatch,
    TopicProjectionRanking,
    TopicMaintenancePlan,
    TopicMaintenanceResult,
    TopicMaintenanceSuggestion,
)
from .messenger_contact import observe_messenger_contact
from .contact_directory import (
    has_mail_contact,
    create_mail_contact,
    split_messenger_contact,
    forget_messenger_contact,
    get_messenger_contact,
    list_messenger_contacts,
    merge_messenger_contacts,
    update_messenger_contact,
)
from .models import DocumentTag, MemoryEmbeddingChunk, MemoryFinding, MemoryItem, MemorySource, MemoryURL
from .urls import associate_memory_url, memory_urls, register_url_reference_merger
from .maintenance import detect_for_item as detect_memory_findings
from .storage import get_storage, register_storage
from .bootstrap import register_memory
from .acquisition_service import acquire_memory
from .deduplication import find_similar_memory_candidates
from .facade import search_memory, search_memory_detailed
from .topic_ranking import rank_topic_projections
from .topic_maintenance import (
    apply_topic_maintenance_plan,
    build_topic_maintenance_plan,
    plan_from_payload as topic_maintenance_plan_from_payload,
    plan_to_payload as topic_maintenance_plan_to_payload,
    topic_maintenance_available,
    topic_maintenance_snapshot_id,
)
from .service import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryPermissionError as MemoryPermissionError,
    ensure_contact_memory_scope,
    ensure_topic_contact_memory_scope,
    ensure_topic_memory_link,
    delete_topic_contact_memory_scopes,
    forget_source_managed_item,
    forget_resource_memories,
    list_topic_linked_memories,
    list_topics_linked_documents,
    move_topic_memory_links,
    move_topic_contact_memory_scopes,
    purge_source_managed_item,
    upsert_source_managed_item,
)
from .contracts import SourceMemoryDocument
from .usage import list_task_memory_usages
from .schemas import (
    MemoryAcquisitionCreate,
    MemoryAcquisitionResult,
    MemoryRecallRequest,
    MemoryRecallResult,
    MemorySearchHit,
    MemorySimilarityCandidate,
)
from .safety import redact_secrets
from .file_facade import (
    append_document_resource_text,
    create_document_attachment_file_resource,
    create_document_file_resource,
    delete_document_attachment_file_resource,
    describe_document_attachment_file_resource,
    describe_file_resource,
    list_document_attachment_file_resources,
    read_document_attachment_file_resource,
    read_file_resource_text,
    search_file_resources,
    write_document_resource_text,
)
from .internal_attachments import register_internal_attachment_reader

__all__ = [
    "forget_resource_memories",
    "rename_document_attachment",
    "register_internal_attachment_reader",
    "AppConsentRequired", "AppWriteLimitError",
    "dataset_budget_reserved",
    "legacy_dataset_access",
    "list_selectable_documents",
    "register_dataset_compatibility", "refresh_dataset_projection", "legacy_dataset_ids", "legacy_dataset_snapshot", "legacy_dataset_exists", "validate_attachment_content",
    "DatasetAttachmentReference", "register_dataset_attachment_reader",
    "DocumentSharingLevelUpdate", "DocumentSharing", "DocumentCollaborator", "resource_sharing_directory", "find_dataset_document_usages",
    "register_document_validator", "create_workflow_document", "read_workflow_document", "write_workflow_document",
    "workflow_document_actor", "workflow_document_access", "workflow_document_readable_ids", "prepare_workflow_document_read", "workflow_history", "workflow_revision", "delete_workflow_revision",
    "restore_workflow_document", "workflow_sharing", "workflow_sharing_preview", "update_workflow_sharing",
    "share_workflow_document",
    "workflow_document_is_orphan",
    "workflow_document_policy_ids",
    "workflow_document_titles",
    "project_catalogue_entry", "link_catalogue_entries", "catalogue_projection_write", "register_source_access",
    "detach_catalogue_parent_links",
    "MemoryTemporalAnchor",
    "DocumentTag",
    "MemoryAccess",
    "MemoryBrief",
    "MemoryContextItem",
    "MemorySearchItem",
    "MemoryConflictError",
    "MemoryNotFoundError",
    "MemoryUsageObservation",
    "ContactReferenceRewriter",
    "ContactReferenceCleaner",
    "MessengerContactIdentity",
    "MessengerContactIdentityInput",
    "MessengerContactObservation",
    "MessengerContactRecord",
    "MemoryAcquisitionCreate",
    "MemoryAcquisitionResult",
    "MemoryRecallRequest",
    "MemoryRecallResult",
    "MemorySearchHit",
    "MemorySimilarityCandidate",
    "MemoryItem",
    "MemoryURL", "associate_memory_url", "memory_urls",
    "register_url_reference_merger",
    "MemoryEmbeddingChunk",
    "MemoryFinding",
    "MemorySource",
    "detect_memory_findings",
    "ResourceStorage",
    "SourceMemoryDocument",
    "TaskMemoryAssociationResult",
    "TopicLinkedMemory",
    "TopicLinkedDocument",
    "TopicProjectionMatch",
    "TopicProjectionRanking",
    "TopicMaintenancePlan",
    "TopicMaintenanceResult",
    "TopicMaintenanceSuggestion",
    "acquire_memory",
    "get_storage",
    "find_similar_memory_candidates",
    "ensure_topic_memory_link",
    "ensure_contact_memory_scope",
    "ensure_topic_contact_memory_scope",
    "delete_topic_contact_memory_scopes",
    "forget_source_managed_item",
    "list_topic_linked_memories",
    "list_topics_linked_documents",
    "move_topic_memory_links",
    "move_topic_contact_memory_scopes",
    "purge_source_managed_item",
    "observe_messenger_contact",
    "get_messenger_contact",
    "forget_messenger_contact",
    "list_messenger_contacts",
    "merge_messenger_contacts",
    "update_messenger_contact",
    "create_mail_contact",
    "has_mail_contact",
    "split_messenger_contact",
    "register_storage",
    "register_memory",
    "upsert_source_managed_item",
    "search_memory",
    "search_memory_detailed",
    "rank_topic_projections",
    "apply_topic_maintenance_plan",
    "build_topic_maintenance_plan",
    "topic_maintenance_available",
    "topic_maintenance_plan_from_payload",
    "topic_maintenance_plan_to_payload",
    "topic_maintenance_snapshot_id",
    "list_task_memory_usages",
    "redact_secrets",
    "append_document_resource_text",
    "create_document_attachment_file_resource",
    "create_document_file_resource",
    "delete_document_attachment_file_resource",
    "describe_document_attachment_file_resource",
    "describe_file_resource",
    "list_document_attachment_file_resources",
    "read_document_attachment_file_resource",
    "read_file_resource_text",
    "search_file_resources",
    "write_document_resource_text",
]

from .events import register_events

register_events()

# Composition: Memory owns the rebuild; model configuration only announces changes.
from app.llm import register_embedding_change_listener
from .semantic_index import enqueue_embedding_reconciliation

register_embedding_change_listener("memory", enqueue_embedding_reconciliation)
