"""Document integration is composed independently of the personal memory backend."""
from app.agent import register_agent_profile_observer, register_scope_collection_resolver
from app.conversation import (register_document_read_authorizer, register_conversation_document_metadata_resolver,
    register_conversation_room_document_creator, register_conversation_room_document_resolver)
from app.goal import register_goal_observer, goal_service
from core.team import register_team_access_observer
from core.user import register_user_access_observer
from .conversation_document_adapter import (authorize_conversation_document_read, create_conversation_room_document,
    resolve_conversation_document_metadata, resolve_conversation_room_documents)
from .goal_document_adapter import register_goal_document_adapter
from .goal_folders import on_access_change, on_document_change, on_goal_change, on_user_change
from .lifecycle import register_document_observer
from .events import register_events
from .resource_service import invalidate_document_views
from .folder_resources import scope_collection_contains


def register_document() -> None:
    register_scope_collection_resolver("document", scope_collection_contains)
    register_scope_collection_resolver("data", scope_collection_contains)
    register_events()
    register_document_read_authorizer(authorize_conversation_document_read)
    register_conversation_document_metadata_resolver(resolve_conversation_document_metadata)
    register_conversation_room_document_resolver(resolve_conversation_room_documents)
    register_conversation_room_document_creator(create_conversation_room_document)
    register_goal_document_adapter()
    register_document_observer("goal_documents", goal_service.handle_goal_document_change)
    register_goal_observer("document_goal_folders",on_goal_change)
    register_document_observer("document_goal_folders",on_document_change)
    register_user_access_observer("document_goal_folders",on_user_change)
    register_team_access_observer("document_goal_folders",on_access_change)
    register_team_access_observer("document_views",invalidate_document_views)

    async def reclassify(_agent_id:int,_action:str) -> None:
        await on_access_change()
    register_agent_profile_observer("document_goal_folders",reclassify)
