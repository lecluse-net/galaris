"""Governed, durable memory public surface."""

from .temporal import MemoryTemporalAnchor
from .facts import AtomicMemoryFact, MemoryFactReference
from .contact_coordinates import ContactCoordinates, ContactPhoneNumber, ContactPostalAddress













from .catalogue_projection import project_catalogue_entry, link_catalogue_entries, catalogue_projection_write, detach_catalogue_parent_links
from .catalogue_projection import identify_catalogue_file as identify_catalogue_file, update_catalogue_file_locations as update_catalogue_file_locations, catalogue_file_summary as catalogue_file_summary
from .indexed_resources import register_indexed_resources as register_indexed_resources
from .federated_ranking import FederatedEvidence, federated_candidate_limit, rank_federated
from .lexical_normalization import folded_sql as folded_lexical_sql
from .passages import lexical_excerpt
from .reference_questions import ReferenceQuestion, parse_reference_question
from .personal_records import PersonalRecordKind, personal_record_for_turn, personal_record_kind
from .source_chronology import (
    SourceChronology, SourceTimeQuery, chronology_from_title, local_source_date,
    mail_source_date_sql, parse_source_time_query, title_dates_sql,
)
from .relevance import fold as fold_lexical
from .relevance import resource_query_terms as resource_query_terms




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
    contact_owner_agent_ids,
    commit_contact_changes,
    lock_messenger_contact,
    create_address_book_contact,
    has_mail_contact,
    indexed_contact_addresses, indexed_contact_identities,
    create_mail_contact,
    split_messenger_contact,
    forget_messenger_contact,
    get_messenger_contact,
    contact_labels,
    list_messenger_contacts,
    list_messenger_contacts_for_owners,
    merge_messenger_contacts,
    update_messenger_contact,
)
from .models import MemoryEmbeddingChunk, MemoryFinding, MemoryItem, MemorySource, MemoryURL
from .urls import associate_memory_url, memory_urls, register_url_reference_merger
from .maintenance import detect_for_item as detect_memory_findings
from core.storage import get_storage, register_storage
from .bootstrap import register_memory
from .acquisition_service import acquire_memory, validate_atomic_fact_references, owned_contact_scope
from .deduplication import find_similar_memory_candidates
from .facade import resolve_recall_scope as resolve_recall_scope, search_memory, search_memory_detailed
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
    record_llm_retrieval,
    purge_source_managed_item,
    upsert_source_managed_item,
)
from .contracts import SourceMemoryDocument
from .usage import list_task_memory_usages
from .schemas import (
    MemoryAcquisitionCreate,
    MemoryAcquisitionResult,
    MemoryRecallRequest,
    MemoryGraphEdge as MemoryGraphEdge,
    MemoryRecallResult,
    MemorySearchHit,
    MemorySimilarityCandidate,
)

from .file_facade import describe_file_resource, read_file_resource_text, search_file_resources


__all__ = [
    "FederatedEvidence",
    "ReferenceQuestion",
    "PersonalRecordKind",
    "personal_record_for_turn",
    "personal_record_kind",
    "SourceChronology",
    "SourceTimeQuery",
    "chronology_from_title",
    "local_source_date",
    "mail_source_date_sql",
    "parse_source_time_query",
    "title_dates_sql",
    "federated_candidate_limit",
    "lexical_excerpt",
    "parse_reference_question",
    "rank_federated",
    "record_llm_retrieval",
    "fold_lexical",
    "folded_lexical_sql",
    "forget_resource_memories",
    "project_catalogue_entry", "link_catalogue_entries", "catalogue_projection_write", "register_source_access",
    "detach_catalogue_parent_links",
    "MemoryTemporalAnchor",
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
    "AtomicMemoryFact", "MemoryFactReference",
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
    "validate_atomic_fact_references",
    "owned_contact_scope",
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
    "contact_labels",
    "forget_messenger_contact",
    "list_messenger_contacts",
    "list_messenger_contacts_for_owners",
    "merge_messenger_contacts",
    "update_messenger_contact",
    "create_mail_contact",
    "create_address_book_contact",
    "contact_owner_agent_ids",
    "commit_contact_changes",
    "lock_messenger_contact",
    "ContactCoordinates",
    "ContactPhoneNumber",
    "ContactPostalAddress",
    "has_mail_contact",
    "indexed_contact_identities",
    "indexed_contact_addresses",
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
    "describe_file_resource",
    "read_file_resource_text",
    "search_file_resources",
]



from .events import register_events
from .safety import redact_secrets as redact_secrets
register_events()

# Composition: Memory owns the rebuild; model configuration only announces changes.
from app.llm import register_embedding_change_listener
from .semantic_index import enqueue_embedding_reconciliation

register_embedding_change_listener("memory", enqueue_embedding_reconciliation)
from .native_content import register_content
register_content()
