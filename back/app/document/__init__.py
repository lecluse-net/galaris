"""Public documentary contracts; implementation imports remain lazy during composition."""
from importlib import import_module
from typing import TYPE_CHECKING
from .models import DocumentSharingIntent as DocumentSharingIntent, DocumentTag as DocumentTag, DocumentTagIcon as DocumentTagIcon, DocumentTagAssignment as DocumentTagAssignment, DocumentNesting as DocumentNesting, DocumentIcon as DocumentIcon, DocumentAppGrant as DocumentAppGrant, DocumentAppWriteBudget as DocumentAppWriteBudget, DocumentListPosition as DocumentListPosition, DocumentAttachment as DocumentAttachment, Document as Document, DocumentRevision as DocumentRevision, DocumentSource as DocumentSource, DocumentAutomationJob as DocumentAutomationJob

if TYPE_CHECKING:
    from . import resource_service as resource_service
    from .lifecycle import register_document_observer as register_document_observer
    from .file_facade import describe_file_resource as describe_file_resource, read_file_resource_text as read_file_resource_text, search_file_resources as search_file_resources
    from .document_app_security import AppConsentRequired as AppConsentRequired
    from .document_app_security import AppWriteLimitError as AppWriteLimitError
    from .dataset_port import register_dataset_compatibility as register_dataset_compatibility
    from .dataset_port import refresh_dataset_projection as refresh_dataset_projection
    from .dataset_port import legacy_dataset_access as legacy_dataset_access
    from .dataset_port import budget_reserved as dataset_budget_reserved
    from .dataset_migration import legacy_dataset_ids as legacy_dataset_ids
    from .dataset_migration import legacy_dataset_snapshot as legacy_dataset_snapshot
    from .dataset_migration import legacy_dataset_exists as legacy_dataset_exists
    from .process_migration import legacy_process_snapshot as legacy_process_snapshot
    from .process_migration import retire_legacy_process_document as retire_legacy_process_document
    from .dataset_references import list_selectable_documents as list_selectable_documents
    from .dataset_attachments import DatasetAttachmentReference as DatasetAttachmentReference
    from .dataset_attachments import register_dataset_attachment_reader as register_dataset_attachment_reader
    from .document_attachment_service import validate_attachment_content as validate_attachment_content
    from .document_attachment_service import rename_document_attachment as rename_document_attachment
    from .document_types import register_document_validator as register_document_validator
    from .schemas import DocumentCollaborator as DocumentCollaborator
    from .schemas import DocumentSharing as DocumentSharing
    from .schemas import DocumentSharingLevelUpdate as DocumentSharingLevelUpdate
    from .item_sharing import sharing_directory as resource_sharing_directory
    from .dataset_usage import find_dataset_document_usages as find_dataset_document_usages
    from .workflow_documents import create_workflow_document as create_workflow_document
    from .workflow_documents import read_workflow_document as read_workflow_document
    from .workflow_documents import write_workflow_document as write_workflow_document
    from .workflow_documents import workflow_document_actor as workflow_document_actor
    from .workflow_documents import workflow_document_access as workflow_document_access
    from .workflow_documents import workflow_document_readable_ids as workflow_document_readable_ids
    from .workflow_documents import prepare_workflow_document_read as prepare_workflow_document_read
    from .workflow_documents import workflow_history as workflow_history
    from .workflow_documents import workflow_revision as workflow_revision
    from .workflow_documents import restore_workflow_document as restore_workflow_document
    from .workflow_documents import delete_workflow_revision as delete_workflow_revision
    from .workflow_documents import workflow_sharing as workflow_sharing
    from .workflow_documents import workflow_sharing_preview as workflow_sharing_preview
    from .workflow_documents import update_workflow_sharing as update_workflow_sharing
    from .workflow_documents import share_workflow_document as share_workflow_document
    from .workflow_documents import workflow_document_is_orphan as workflow_document_is_orphan
    from .workflow_documents import workflow_document_policy_ids as workflow_document_policy_ids
    from .workflow_documents import workflow_document_titles as workflow_document_titles
    from .document_thumbnail_service import render_file_thumbnail as render_file_thumbnail
    from .document_thumbnail_service import generate_document_attachment_thumbnail as generate_document_attachment_thumbnail
    from .document_thumbnail_service import read_document_thumbnail as read_document_thumbnail
    from .schemas import DocumentThumbnailRender as DocumentThumbnailRender
    from .safety import redact_secrets as redact_secrets
    from .file_facade import append_document_resource_text as append_document_resource_text
    from .file_facade import create_document_attachment_file_resource as create_document_attachment_file_resource
    from .file_facade import create_document_file_resource as create_document_file_resource
    from .file_facade import delete_document_attachment_file_resource as delete_document_attachment_file_resource
    from .file_facade import describe_document_attachment_file_resource as describe_document_attachment_file_resource
    from .file_facade import list_document_attachment_file_resources as list_document_attachment_file_resources
    from .file_facade import read_document_attachment_file_resource as read_document_attachment_file_resource
    from .file_facade import write_document_resource_text as write_document_resource_text
    from .internal_attachments import register_internal_attachment_reader as register_internal_attachment_reader
    from .events import register_events as register_events
    from .resource_service import DocumentError as DocumentError
    from .resource_service import DocumentNotFoundError as DocumentNotFoundError
    from .resource_service import DocumentPermissionError as DocumentPermissionError
    from .resource_service import DocumentConflictError as DocumentConflictError
    from .resource_service import update_summary as update_summary
    from .resource_service import get_item as get_item
    from .resource_service import get_item_metadata as get_item_metadata
    from .resource_service import item_record as item_record
    from .resource_service import item_to_detail as item_to_detail
    from .resource_service import item_to_public as item_to_public
    from .resource_service import delete_document as delete_document
    from .resource_service import update_item as update_item
    from .resource_service import source_refs as source_refs
    from .contracts import DocumentAccess as DocumentAccess
    from .contracts import DatasetDocumentGrant as DatasetDocumentGrant
    from .contracts import DatasetDocumentProjection as DatasetDocumentProjection
    from .contracts import DatasetProjectionWriter as DatasetProjectionWriter
    from .topic_assignment import assignment as document_topic_assignment
    from .topic_assignment import change_assignment as change_document_topic
    from .topic_assignment import count_pending as count_pending_topic_documents
    from .topic_assignment import claim_one as claim_topic_document
    from .topic_assignment import source as topic_document_source
    from .topic_assignment import is_current as topic_document_is_current
    from .topic_assignment import assign as assign_document_topic
    from .topic_assignment import list_related as list_documents_by_topics
    from .topic_assignment import reassign as reassign_topic_documents
    from .schemas import DocumentPayload as DocumentPayload
    from .schemas import DocumentUpdate as DocumentUpdate
    from .schemas import DocumentPublic as DocumentPublic
    from .schemas import DocumentDetail as DocumentDetail
    from .schemas import DocumentItemCreate as DocumentItemCreate
    from .schemas import DocumentSourceCreate as DocumentSourceCreate
    from .schemas import DocumentDeletionResult as DocumentDeletionResult
    from .schemas import ManagedDocumentDetail as ManagedDocumentDetail
    from .goal_folders import enqueue_goal_folder_reconciliation as enqueue_goal_folder_reconciliation
    from .bootstrap import register_document as register_document
    from .models import DocumentSharingIntent as DocumentSharingIntent
    from .models import DocumentTag as DocumentTag
    from .models import DocumentTagIcon as DocumentTagIcon
    from .models import DocumentTagAssignment as DocumentTagAssignment
    from .models import DocumentNesting as DocumentNesting
    from .models import DocumentIcon as DocumentIcon
    from .models import DocumentAppGrant as DocumentAppGrant
    from .models import DocumentAppWriteBudget as DocumentAppWriteBudget
    from .models import DocumentListPosition as DocumentListPosition
    from .models import DocumentAttachment as DocumentAttachment
    from .models import Document as Document
    from .models import DocumentRevision as DocumentRevision
    from .models import DocumentSource as DocumentSource
    from .models import DocumentAutomationJob as DocumentAutomationJob

_EXPORTS = {'resource_service': ('resource_service', ''),'register_document_observer':('lifecycle','register_document_observer'),'describe_file_resource': ('file_facade','describe_file_resource'), 'read_file_resource_text': ('file_facade','read_file_resource_text'), 'search_file_resources': ('file_facade','search_file_resources'), 'AppConsentRequired': ('document_app_security', 'AppConsentRequired'), 'AppWriteLimitError': ('document_app_security', 'AppWriteLimitError'), 'register_dataset_compatibility': ('dataset_port', 'register_dataset_compatibility'), 'refresh_dataset_projection': ('dataset_port', 'refresh_dataset_projection'), 'legacy_dataset_access': ('dataset_port', 'legacy_dataset_access'), 'dataset_budget_reserved': ('dataset_port', 'budget_reserved'), 'legacy_dataset_ids': ('dataset_migration', 'legacy_dataset_ids'), 'legacy_dataset_snapshot': ('dataset_migration', 'legacy_dataset_snapshot'), 'legacy_dataset_exists': ('dataset_migration', 'legacy_dataset_exists'), 'legacy_process_snapshot': ('process_migration', 'legacy_process_snapshot'), 'retire_legacy_process_document': ('process_migration', 'retire_legacy_process_document'), 'list_selectable_documents': ('dataset_references', 'list_selectable_documents'), 'DatasetAttachmentReference': ('dataset_attachments', 'DatasetAttachmentReference'), 'register_dataset_attachment_reader': ('dataset_attachments', 'register_dataset_attachment_reader'), 'validate_attachment_content': ('document_attachment_service', 'validate_attachment_content'), 'rename_document_attachment': ('document_attachment_service', 'rename_document_attachment'), 'register_document_validator': ('document_types', 'register_document_validator'), 'DocumentCollaborator': ('schemas', 'DocumentCollaborator'), 'DocumentSharing': ('schemas', 'DocumentSharing'), 'DocumentSharingLevelUpdate': ('schemas', 'DocumentSharingLevelUpdate'), 'resource_sharing_directory': ('item_sharing', 'sharing_directory'), 'find_dataset_document_usages': ('dataset_usage', 'find_dataset_document_usages'), 'create_workflow_document': ('workflow_documents', 'create_workflow_document'), 'read_workflow_document': ('workflow_documents', 'read_workflow_document'), 'write_workflow_document': ('workflow_documents', 'write_workflow_document'), 'workflow_document_actor': ('workflow_documents', 'workflow_document_actor'), 'workflow_document_access': ('workflow_documents', 'workflow_document_access'), 'workflow_document_readable_ids': ('workflow_documents', 'workflow_document_readable_ids'), 'prepare_workflow_document_read': ('workflow_documents', 'prepare_workflow_document_read'), 'workflow_history': ('workflow_documents', 'workflow_history'), 'workflow_revision': ('workflow_documents', 'workflow_revision'), 'restore_workflow_document': ('workflow_documents', 'restore_workflow_document'), 'delete_workflow_revision': ('workflow_documents', 'delete_workflow_revision'), 'workflow_sharing': ('workflow_documents', 'workflow_sharing'), 'workflow_sharing_preview': ('workflow_documents', 'workflow_sharing_preview'), 'update_workflow_sharing': ('workflow_documents', 'update_workflow_sharing'), 'share_workflow_document': ('workflow_documents', 'share_workflow_document'), 'workflow_document_is_orphan': ('workflow_documents', 'workflow_document_is_orphan'), 'workflow_document_policy_ids': ('workflow_documents', 'workflow_document_policy_ids'), 'workflow_document_titles': ('workflow_documents', 'workflow_document_titles'), 'render_file_thumbnail': ('document_thumbnail_service', 'render_file_thumbnail'), 'generate_document_attachment_thumbnail': ('document_thumbnail_service', 'generate_document_attachment_thumbnail'), 'read_document_thumbnail': ('document_thumbnail_service', 'read_document_thumbnail'), 'DocumentThumbnailRender': ('schemas', 'DocumentThumbnailRender'), 'redact_secrets': ('safety', 'redact_secrets'), 'append_document_resource_text': ('file_facade', 'append_document_resource_text'), 'create_document_attachment_file_resource': ('file_facade', 'create_document_attachment_file_resource'), 'create_document_file_resource': ('file_facade', 'create_document_file_resource'), 'delete_document_attachment_file_resource': ('file_facade', 'delete_document_attachment_file_resource'), 'describe_document_attachment_file_resource': ('file_facade', 'describe_document_attachment_file_resource'), 'list_document_attachment_file_resources': ('file_facade', 'list_document_attachment_file_resources'), 'read_document_attachment_file_resource': ('file_facade', 'read_document_attachment_file_resource'), 'write_document_resource_text': ('file_facade', 'write_document_resource_text'), 'register_internal_attachment_reader': ('internal_attachments', 'register_internal_attachment_reader'), 'register_events': ('events', 'register_events'), 'DocumentError': ('resource_service', 'DocumentError'), 'DocumentNotFoundError': ('resource_service', 'DocumentNotFoundError'), 'DocumentPermissionError': ('resource_service', 'DocumentPermissionError'), 'DocumentConflictError': ('resource_service', 'DocumentConflictError'), 'update_summary': ('resource_service', 'update_summary'), 'get_item': ('resource_service', 'get_item'), 'get_item_metadata': ('resource_service', 'get_item_metadata'), 'item_record': ('resource_service', 'item_record'), 'item_to_detail': ('resource_service', 'item_to_detail'), 'item_to_public': ('resource_service', 'item_to_public'), 'delete_document': ('resource_service', 'delete_document'), 'update_item': ('resource_service', 'update_item'), 'source_refs': ('resource_service', 'source_refs'), 'DocumentAccess': ('contracts', 'DocumentAccess'), 'DatasetDocumentGrant': ('contracts', 'DatasetDocumentGrant'), 'DatasetDocumentProjection': ('contracts', 'DatasetDocumentProjection'), 'DatasetProjectionWriter': ('contracts', 'DatasetProjectionWriter'), 'document_topic_assignment': ('topic_assignment', 'assignment'), 'change_document_topic': ('topic_assignment', 'change_assignment'), 'count_pending_topic_documents': ('topic_assignment', 'count_pending'), 'claim_topic_document': ('topic_assignment', 'claim_one'), 'topic_document_source': ('topic_assignment', 'source'), 'topic_document_is_current': ('topic_assignment', 'is_current'), 'assign_document_topic': ('topic_assignment', 'assign'), 'list_documents_by_topics': ('topic_assignment', 'list_related'), 'reassign_topic_documents': ('topic_assignment', 'reassign'), 'DocumentPayload': ('schemas', 'DocumentPayload'), 'DocumentUpdate': ('schemas', 'DocumentUpdate'), 'DocumentPublic': ('schemas', 'DocumentPublic'), 'DocumentDetail': ('schemas', 'DocumentDetail'), 'DocumentItemCreate': ('schemas', 'DocumentItemCreate'), 'DocumentSourceCreate': ('schemas', 'DocumentSourceCreate'), 'DocumentDeletionResult': ('schemas', 'DocumentDeletionResult'), 'ManagedDocumentDetail': ('schemas', 'ManagedDocumentDetail'), 'enqueue_goal_folder_reconciliation': ('goal_folders', 'enqueue_goal_folder_reconciliation'), 'register_document': ('bootstrap', 'register_document'), 'DocumentSharingIntent': ('models', 'DocumentSharingIntent'), 'DocumentTag': ('models', 'DocumentTag'), 'DocumentTagIcon': ('models', 'DocumentTagIcon'), 'DocumentTagAssignment': ('models', 'DocumentTagAssignment'), 'DocumentNesting': ('models', 'DocumentNesting'), 'DocumentIcon': ('models', 'DocumentIcon'), 'DocumentAppGrant': ('models', 'DocumentAppGrant'), 'DocumentAppWriteBudget': ('models', 'DocumentAppWriteBudget'), 'DocumentListPosition': ('models', 'DocumentListPosition'), 'DocumentAttachment': ('models', 'DocumentAttachment'), 'Document': ('models', 'Document'), 'DocumentRevision': ('models', 'DocumentRevision'), 'DocumentSource': ('models', 'DocumentSource'), 'DocumentAutomationJob': ('models', 'DocumentAutomationJob')}

__all__ = ['resource_service','register_document_observer','describe_file_resource','read_file_resource_text','search_file_resources','AppConsentRequired', 'AppWriteLimitError', 'register_dataset_compatibility', 'refresh_dataset_projection', 'legacy_dataset_access', 'dataset_budget_reserved', 'legacy_dataset_ids', 'legacy_dataset_snapshot', 'legacy_dataset_exists', 'legacy_process_snapshot', 'retire_legacy_process_document', 'list_selectable_documents', 'DatasetAttachmentReference', 'register_dataset_attachment_reader', 'validate_attachment_content', 'rename_document_attachment', 'register_document_validator', 'DocumentCollaborator', 'DocumentSharing', 'DocumentSharingLevelUpdate', 'resource_sharing_directory', 'find_dataset_document_usages', 'create_workflow_document', 'read_workflow_document', 'write_workflow_document', 'workflow_document_actor', 'workflow_document_access', 'workflow_document_readable_ids', 'prepare_workflow_document_read', 'workflow_history', 'workflow_revision', 'restore_workflow_document', 'delete_workflow_revision', 'workflow_sharing', 'workflow_sharing_preview', 'update_workflow_sharing', 'share_workflow_document', 'workflow_document_is_orphan', 'workflow_document_policy_ids', 'workflow_document_titles', 'render_file_thumbnail', 'generate_document_attachment_thumbnail', 'read_document_thumbnail', 'DocumentThumbnailRender', 'redact_secrets', 'append_document_resource_text', 'create_document_attachment_file_resource', 'create_document_file_resource', 'delete_document_attachment_file_resource', 'describe_document_attachment_file_resource', 'list_document_attachment_file_resources', 'read_document_attachment_file_resource', 'write_document_resource_text', 'register_internal_attachment_reader', 'register_events', 'DocumentError', 'DocumentNotFoundError', 'DocumentPermissionError', 'DocumentConflictError', 'update_summary', 'get_item', 'get_item_metadata', 'item_record', 'item_to_detail', 'item_to_public', 'delete_document', 'update_item', 'source_refs', 'DocumentAccess', 'DatasetDocumentGrant', 'DatasetDocumentProjection', 'DatasetProjectionWriter', 'document_topic_assignment', 'change_document_topic', 'count_pending_topic_documents', 'claim_topic_document', 'topic_document_source', 'topic_document_is_current', 'assign_document_topic', 'list_documents_by_topics', 'reassign_topic_documents', 'DocumentPayload', 'DocumentUpdate', 'DocumentPublic', 'DocumentDetail', 'DocumentItemCreate', 'DocumentSourceCreate', 'DocumentDeletionResult', 'ManagedDocumentDetail', 'enqueue_goal_folder_reconciliation', 'register_document', 'DocumentSharingIntent', 'DocumentTag', 'DocumentTagIcon', 'DocumentTagAssignment', 'DocumentNesting', 'DocumentIcon', 'DocumentAppGrant', 'DocumentAppWriteBudget', 'DocumentListPosition', 'DocumentAttachment', 'Document', 'DocumentRevision', 'DocumentSource', 'DocumentAutomationJob', 'register_web_thumbnail_capture']

def __getattr__(name: str) -> object:
    binding = _EXPORTS.get(name)
    if binding is None:
        raise AttributeError(name)
    module, attribute = binding
    target = import_module(f"{__package__}.{module}")
    value = getattr(target, attribute) if attribute else target
    globals()[name] = value
    return value

from .inline_content import register_content
register_content()
from .search_index import register_document_search as register_document_search
__all__.append("register_document_search")
if TYPE_CHECKING:
    from .models import DocumentURL as DocumentURL
_EXPORTS["DocumentURL"] = ("models", "DocumentURL")
__all__.append("DocumentURL")
if TYPE_CHECKING:
    from .document_thumbnail_service import register_web_thumbnail_capture as register_web_thumbnail_capture
_EXPORTS["register_web_thumbnail_capture"]=("document_thumbnail_service","register_web_thumbnail_capture")

from .resource_summaries import (
    count_pending as count_pending_document_summaries, claim_one as claim_document_summary,
    source as document_summary_source, apply as apply_document_summary,
    reconcile as reconcile_document_summaries,
)
__all__ += ["count_pending_document_summaries", "claim_document_summary", "document_summary_source",
            "apply_document_summary", "reconcile_document_summaries"]
