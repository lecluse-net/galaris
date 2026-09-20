"""Priority conversation control plane.

Human messages are grouped into durable room-scoped rounds and executed independently from the
Task scheduler. Concrete LLM runtimes register through :mod:`app.conversation.controller`.

Messenger rooms and messages are the only persisted conversational scope and content.
"""

from .contracts import (
    ConversationController,
    ConversationActivity,
    ConversationActivityDetail,
    ConversationActivityInteraction,
    ConversationActivityPage,
    ConversationDocument,
    ConversationDocumentList,
    ConversationProcessList,
    ConversationTask,
    ConversationTaskTree,
    ConversationExecutionError,
    ConversationOutcome,
    ConversationProgressPublisher,
    ConversationProgressResetter,
    ConversationRuntimeEvent,
    ConversationTurn,
    FreshnessGuard,
    public_ai_message,
    public_ai_result,
)
from .controller import register_controller
from .preparation import ConversationSuperseded, run_preparation
from .document_display import (
    can_display_conversation_document,
    display_conversation_document,
    register_document_display_publisher,
    register_document_read_authorizer,
)
from .runtime import ConversationRuntimeStream
from .directives import (
    ChatDirective,
    get_agent_chat_directives,
    parse_direct_task_directive,
)
from .context import register_recent_conversation_document_context
from .document_metadata import (
    ConversationDocumentMetadata,
    ConversationDocumentMetadataResolver,
    create_conversation_room_document,
    register_conversation_document_metadata_resolver,
    resolve_conversation_document_metadata,
    register_conversation_room_document_creator,
    register_conversation_room_document_resolver,
)
from .facade import (
    admit_messenger_input,
    publish_round_activity,
    publish_runtime_event,
    register_activity_listener,
    register_runtime,
    register_runtime_listener,
    wake,
)
from .inspection_service import inspect_round as inspect_conversation_round
from .resource_facade import (
    list_conversation_round_resources,
    read_conversation_round_resource,
)
from .activity_facade import get_room_activity_detail, list_room_activity
from .task_projection import list_room_tasks
from .work_projection import list_room_documents, list_room_processes
from .models import (
    ConversationProcessLink,
    ConversationRound,
    ConversationRoundAttempt,
    ConversationRoundMessage,
    ConversationTaskLink,
)
from .service import linked_work_snapshot

__all__ = [
    "ConversationSuperseded",
    "run_preparation",
    "can_display_conversation_document",
    "display_conversation_document",
    "register_document_display_publisher",
    "register_document_read_authorizer",
    "ConversationController",
    "ConversationActivity",
    "ConversationActivityDetail",
    "ConversationActivityInteraction",
    "ConversationActivityPage",
    "ConversationDocument",
    "ConversationDocumentList",
    "ConversationProcessList",
    "ConversationTask",
    "ConversationTaskTree",
    "ConversationExecutionError",
    "ConversationOutcome",
    "ConversationProgressPublisher",
    "ConversationProgressResetter",
    "ConversationRuntimeEvent",
    "ConversationRuntimeStream",
    "ConversationProcessLink",
    "ConversationRound",
    "ConversationRoundAttempt",
    "ConversationRoundMessage",
    "ConversationTaskLink",
    "ConversationTurn",
    "ChatDirective",
    "FreshnessGuard",
    "public_ai_message",
    "public_ai_result",
    "admit_messenger_input",
    "register_controller",
    "register_recent_conversation_document_context",
    "ConversationDocumentMetadata",
    "ConversationDocumentMetadataResolver",
    "create_conversation_room_document",
    "register_conversation_document_metadata_resolver",
    "resolve_conversation_document_metadata",
    "register_conversation_room_document_creator",
    "register_conversation_room_document_resolver",
    "register_runtime",
    "inspect_conversation_round",
    "list_conversation_round_resources",
    "list_room_activity",
    "get_room_activity_detail",
    "get_agent_chat_directives",
    "list_room_tasks",
    "list_room_documents",
    "list_room_processes",
    "linked_work_snapshot",
    "read_conversation_round_resource",
    "publish_round_activity",
    "publish_runtime_event",
    "parse_direct_task_directive",
    "register_activity_listener",
    "register_runtime_listener",
    "wake",
]
