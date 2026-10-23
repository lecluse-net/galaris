"""Public SQL admission for source references; no Memory implementation dependency."""
from uuid import UUID
from collections.abc import Collection
from sqlalchemy import select, Select
from .models import Document
from . import access
from .contracts import DocumentAccess
from core.user import HumanActor


def readable_ids(agent_id: int) -> Select[tuple[UUID]]:
    return select(Document.id).where(access.readable_item_clause(agent_id)).correlate(None)


def readable_ids_for_agents(agent_ids: Collection[int] | None) -> Select[tuple[UUID]]:
    return select(Document.id).where(access.readable_item_for_agents_clause(agent_ids)).correlate(None)


def human_ids(user_id: int, *, write: bool = False) -> Select[tuple[UUID]]:
    return select(Document.id).where(access.human_item_clause(user_id, write=write)).correlate(None)


async def document_access(identity: UUID, actor: int | HumanActor) -> DocumentAccess:
    from core.database import get_db
    document=await get_db().get(Document,identity)
    if document is None or document.deleted_at is not None:
        return DocumentAccess(False,False)
    return await access.effective_access(document,actor)


async def document_access_many(identities: Collection[UUID], actor: int) -> dict[UUID, DocumentAccess]:
    from core.database import get_db
    if not identities:
        return {}
    rows = await get_db().execute(select(Document.id, access.readable_item_clause(actor),
        access.writable_item_clause(actor)).where(Document.id.in_(identities)))
    return {identity: DocumentAccess(bool(read), bool(write)) for identity, read, write in rows}


async def managed_agents(identity: UUID, agents: Collection[int] | None) -> tuple[tuple[int,...],tuple[int,...]]:
    from core.database import get_db
    item=await get_db().get(Document,identity)
    return await access.managed_item_agent_ids(item,agents) if item is not None else ((),())


from .access import document_team_agent_access as document_team_agent_access
from .document_policy import document_policy_clause as document_policy_clause

from typing import TYPE_CHECKING
from importlib import import_module
if TYPE_CHECKING:
    from .document_app_security import AppConsentRequired as AppConsentRequired
    from .document_app_security import AppWriteLimitError as AppWriteLimitError
    from .document_app_service import app_dataset as app_dataset
    from .document_app_service import app_permissions as app_permissions
    from .document_app_service import set_app_permission as set_app_permission
    from .document_apps import AppDatasetRequest as AppDatasetRequest
    from .document_apps import AppDatasetResult as AppDatasetResult
    from .document_apps import AppGrantUpdate as AppGrantUpdate
    from .document_apps import AppPermissions as AppPermissions
    from .assertions import ManagedDocumentAccessAssertion as ManagedDocumentAccessAssertion
    from . import item_sharing as item_sharing
    from . import document_sharing as document_sharing
    from . import document_tags as document_tags
    from . import document_service as document_service
    from . import document_export as document_export
    from . import document_attachment_service as document_attachment_service
    from . import dataset_attachments as dataset_attachments
    from . import process_references as process_references
    from . import internal_attachments as internal_attachments
    from . import document_thumbnail_service as document_thumbnail_service
    from .document_tags import lock_tree as lock_tree
    from .sharing_inheritance import lock_sharing as lock_sharing
    from .sharing_inheritance import prepare_own_sharing as prepare_own_sharing
    from .sharing_inheritance import finish_own_sharing as finish_own_sharing
    from .dataset_port import dataset_compatibility as dataset_compatibility
    from .document_backup import archived_resources as archived_resources
    from .sharing_inheritance import reconcile_sharing as reconcile_sharing
    from .document_attachment_service import attachments_from_item as attachments_from_item
    from .revision_queries import content_revision as content_revision
    from .revision_queries import content_revision_page as content_revision_page
    from .document_thumbnail_service import cleanup_current_document_thumbnail as cleanup_current_document_thumbnail
    from .content_diff import content_diff_hunks as content_diff_hunks
    from .document_apps import document_apps as document_apps
    from .document_types import validate_document_content as validate_document_content
    from .document_types import DocumentType as DocumentType
    from .tag_icons import SVG_PREFIX as SVG_PREFIX
    from .tag_icons import validate_icon as validate_icon
    from .document_library_filters import library_filters as library_filters
    from .document_backup import backup_documents as backup_documents
    from .document_backup import document_backup_complete as document_backup_complete
    from .document_backup import needs_document_backup as needs_document_backup
    from .document_backup import verify_unchanged_sources as verify_unchanged_sources
    from .goal_folders import GoalFolderRequest as GoalFolderRequest
    from .goal_folders import process_goal_folder_job as process_goal_folder_job

_BINDINGS = {'AppConsentRequired': ('document_app_security', 'AppConsentRequired'), 'AppWriteLimitError': ('document_app_security', 'AppWriteLimitError'), 'app_dataset': ('document_app_service', 'app_dataset'), 'app_permissions': ('document_app_service', 'app_permissions'), 'set_app_permission': ('document_app_service', 'set_app_permission'), 'AppDatasetRequest': ('document_apps', 'AppDatasetRequest'), 'AppDatasetResult': ('document_apps', 'AppDatasetResult'), 'AppGrantUpdate': ('document_apps', 'AppGrantUpdate'), 'AppPermissions': ('document_apps', 'AppPermissions'), 'ManagedDocumentAccessAssertion': ('assertions', 'ManagedDocumentAccessAssertion'), 'item_sharing': ('item_sharing', ''), 'document_sharing': ('document_sharing', ''), 'document_tags': ('document_tags', ''), 'document_service': ('document_service', ''), 'document_export': ('document_export', ''), 'document_attachment_service': ('document_attachment_service', ''), 'dataset_attachments': ('dataset_attachments', ''), 'process_references': ('process_references', ''), 'internal_attachments': ('internal_attachments', ''), 'document_thumbnail_service': ('document_thumbnail_service', ''), 'lock_tree': ('document_tags', 'lock_tree'), 'lock_sharing': ('sharing_inheritance', 'lock_sharing'), 'prepare_own_sharing': ('sharing_inheritance', 'prepare_own_sharing'), 'finish_own_sharing': ('sharing_inheritance', 'finish_own_sharing'), 'dataset_compatibility': ('dataset_port', 'dataset_compatibility'), 'archived_resources': ('document_backup', 'archived_resources'), 'reconcile_sharing': ('sharing_inheritance', 'reconcile_sharing'), 'attachments_from_item': ('document_attachment_service', 'attachments_from_item'), 'content_revision': ('revision_queries', 'content_revision'), 'content_revision_page': ('revision_queries', 'content_revision_page'), 'cleanup_current_document_thumbnail': ('document_thumbnail_service', 'cleanup_current_document_thumbnail'), 'content_diff_hunks': ('content_diff', 'content_diff_hunks'), 'document_apps': ('document_apps', 'document_apps'), 'validate_document_content': ('document_types', 'validate_document_content'), 'DocumentType': ('document_types', 'DocumentType'), 'SVG_PREFIX': ('tag_icons', 'SVG_PREFIX'), 'validate_icon': ('tag_icons', 'validate_icon'), 'library_filters': ('document_library_filters', 'library_filters'), 'backup_documents': ('document_backup', 'backup_documents'), 'document_backup_complete': ('document_backup', 'document_backup_complete'), 'needs_document_backup': ('document_backup', 'needs_document_backup'), 'verify_unchanged_sources': ('document_backup', 'verify_unchanged_sources'), 'GoalFolderRequest': ('goal_folders', 'GoalFolderRequest'), 'process_goal_folder_job': ('goal_folders', 'process_goal_folder_job')}

def __getattr__(name: str) -> object:
    if name not in _BINDINGS:
        raise AttributeError(name)
    module,attribute=_BINDINGS[name]
    target=import_module(f"{__package__}.{module}")
    value=getattr(target,attribute) if attribute else target
    globals()[name]=value
    return value

__all__ = ['readable_ids', 'readable_ids_for_agents', 'human_ids', 'document_access', 'managed_agents', 'document_team_agent_access', 'AppConsentRequired', 'AppWriteLimitError', 'app_dataset', 'app_permissions', 'set_app_permission', 'AppDatasetRequest', 'AppDatasetResult', 'AppGrantUpdate', 'AppPermissions', 'ManagedDocumentAccessAssertion', 'item_sharing', 'document_sharing', 'document_tags', 'document_service', 'document_export', 'document_attachment_service', 'dataset_attachments', 'process_references', 'internal_attachments', 'document_thumbnail_service', 'lock_tree', 'lock_sharing', 'prepare_own_sharing', 'finish_own_sharing', 'dataset_compatibility', 'archived_resources', 'reconcile_sharing', 'attachments_from_item', 'content_revision', 'content_revision_page', 'cleanup_current_document_thumbnail', 'content_diff_hunks', 'document_apps', 'validate_document_content', 'DocumentType', 'SVG_PREFIX', 'validate_icon', 'library_filters', 'backup_documents', 'document_backup_complete', 'needs_document_backup', 'verify_unchanged_sources', 'GoalFolderRequest', 'process_goal_folder_job']
