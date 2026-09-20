"""Composition hooks for long-term context and background automation."""

from __future__ import annotations

from uuid import UUID

from app.agent import (
    register_agent_profile_observer,
    register_context_provider,
)
from app.agent.contracts import (
    AgentContextCandidate,
    AgentContextContribution,
    AgentContextRequest,
)
from core.params import params_service
from core.params.consts import Params
from core.params import runtime_settings

from .context import (
    build_memory_brief,
    memory_context_query,
    memory_context_semantic_query,
    memory_policy_instructions,
)
from .service import projected_topic_item_id


_MAINTENANCE_THRESHOLD_PARAMS = frozenset(
    {
        Params.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD,
        Params.MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD,
        Params.MEMORY_AGING_AFTER_DAYS,
    }
)


async def on_memory_parameter_change(name: str, _value: str | None) -> None:
    """Reconcile visible findings after a persisted threshold change."""

    if name not in _MAINTENANCE_THRESHOLD_PARAMS:
        return
    from .maintenance import reconcile_policy_findings

    await reconcile_policy_findings()


def _contact_terms(request: AgentContextRequest) -> tuple[str, ...]:
    """Return exact, server-owned contact terms without importing Messenger."""

    data = request.task_data
    if bool(data.get("sender_is_ai")):
        return ()
    user_id = str(
        data.get("sender.user_id")
        or data.get("sender.id")
        or data.get("user_id")
        or ""
    ).strip()
    if not user_id:
        return ()
    display_name = str(
        data.get("sender.display_name")
        or data.get("sender.nickname")
        or ""
    ).strip()
    platform = str(request.message_platform or "").strip()
    return tuple(value for value in (display_name, user_id, platform) if value)


async def memory_context_provider(
    request: AgentContextRequest,
) -> AgentContextContribution:
    if not request.include_historical_context:
        return AgentContextContribution(
            metadata={
                "memory_context_enabled": False,
                "memory_context_count": 0,
                "memory_context_truncated": False,
                "memory_context_skipped": "standalone_objective",
            }
        )
    if not runtime_settings.MEMORY_CONTEXT_ENABLED:
        return AgentContextContribution(
            metadata={
                "memory_context_enabled": False,
                "memory_context_count": 0,
                "memory_context_truncated": False,
            }
        )
    query = memory_context_query(
        label=request.label,
        objective=request.objective,
        # The exact contact UUID is the identity boundary. Repeating display names,
        # platform handles and bridge codes in the semantic query dilutes its topic.
        contact_terms=(
            ()
            if request.contact_memory_item_id is not None
            else _contact_terms(request)
        ),
    )
    semantic_query = memory_context_semantic_query(
        label=request.label,
        objective=request.objective,
        conversation_history=request.available_history,
    )
    human_messenger = bool(request.messenger_connection_id) and not bool(
        request.task_data.get("sender_is_ai")
    )
    # The continuity capsule for a human excludes memories owned by another
    # contact, but keeps ordinary unscoped memories available. Dream may
    # assign or revise a Topic later; it must not become an accidental
    # retrieval boundary for the interlocutor history.
    topic_item_id = (
        None
        if human_messenger
        else await projected_topic_item_id(request.topic_id)
    )
    brief = await build_memory_brief(
        agent_id=request.agent.id,
        query=query,
        semantic_query=semantic_query,
        task_id=request.task_id,
        topic_item_id=topic_item_id,
        contact_item_id=request.contact_memory_item_id,
        # Non-strict contact recall means "this contact plus unscoped". It
        # still excludes every memory owned by another contact. Strict mode
        # used to discard all of the agent's global memory in conversation
        # rounds, which made the same ranked search appear almost empty.
        strict_contact_scope=False,
        include_relevant=(
            not human_messenger or request.contact_memory_item_id is not None
        ),
        # Outcome learning now produces dedicated app.skill records. Historical
        # Memory experience nodes remain readable for compatibility but are no
        # longer injected automatically.
        include_experience=False,
        stage=request.stage,
    )
    if not brief.rendered:
        return AgentContextContribution(
            system_instructions=memory_policy_instructions(),
            metadata={
                "memory_context_enabled": True,
                "memory_context_query": query,
                "memory_context_count": 0,
                "memory_context_truncated": False,
            },
        )
    candidates = tuple(
        AgentContextCandidate(
            key=f"memory:{item.memory_id}",
            kind="memory",
            reference=item.memory_id,
            title=item.title,
            excerpt=item.excerpt,
            revision=item.revision,
            base_score=max(0.0, min(1.0, item.score)),
            provenance=item.source_refs,
            metadata={
                "memory_type": item.memory_type,
                "node_kind": item.node_kind,
                "uri": f"{'document' if item.node_kind == 'document' else 'memory'}://{item.memory_id}",
            },
        )
        for item in brief.items
    )
    return AgentContextContribution(
        system_instructions=memory_policy_instructions(),
        shared_context=(
            ""
            if request.contact_memory_item_id is not None
            else brief.rendered
        ),
        memory_context=(
            ""
            if request.contact_memory_item_id is not None
            else brief.rendered
        ),
        candidates=candidates,
        metadata={
            "memory_context_enabled": True,
            "memory_context_query": query,
            "memory_context_ids": [item.memory_id for item in brief.items],
            "memory_context_count": len(brief.items),
            "memory_context_truncated": brief.truncated,
            "memory_context_rendered": brief.rendered,
        },
    )


def register_memory() -> None:
    """Register governed-memory context at the composition root."""
    from . import service

    register_context_provider("long_term_memory", memory_context_provider, priority=20,
                              refreshes_frozen_kinds=frozenset({"memory"}))
    params_service.register_change_listener(on_memory_parameter_change)
    from app.conversation import (
        register_document_read_authorizer,
        register_conversation_document_metadata_resolver,
        register_conversation_room_document_creator,
        register_conversation_room_document_resolver,
    )

    from .conversation_document_adapter import (
        authorize_conversation_document_read,
        create_conversation_room_document,
        resolve_conversation_document_metadata,
        resolve_conversation_room_documents,
    )
    from .goal_document_adapter import register_goal_document_adapter
    from .lifecycle import register_memory_item_observer
    from app.goal.goal_service import handle_goal_document_change

    register_document_read_authorizer(authorize_conversation_document_read)
    register_conversation_document_metadata_resolver(
        resolve_conversation_document_metadata
    )
    register_conversation_room_document_resolver(resolve_conversation_room_documents)
    register_conversation_room_document_creator(create_conversation_room_document)
    register_goal_document_adapter()
    register_memory_item_observer("goal_documents", handle_goal_document_change)
    from .automation import enqueue_source_projection
    from app.goal import register_goal_observer

    async def project_agent(agent_id: int, action: str) -> None:
        await enqueue_source_projection("agent", str(agent_id), action)
        await service.invalidate_memory_views()

    async def project_goal(goal_id: UUID, action: str) -> None:
        await enqueue_source_projection("goal", str(goal_id), action)

    register_agent_profile_observer("memory_projection", project_agent)
    register_goal_observer("memory_projection", project_goal)
    from core.team import register_team_access_observer
    register_team_access_observer("memory_views", service.invalidate_memory_views)
    from core.user import register_user_access_observer
    from .goal_folders import on_access_change, on_document_change, on_goal_change, on_user_change

    async def reclassify_agent_documents(_agent_id: int, _action: str) -> None:
        await on_access_change()

    register_goal_observer("memory_goal_folders", on_goal_change)
    register_memory_item_observer("memory_goal_folders", on_document_change)
    register_user_access_observer("memory_goal_folders", on_user_change)
    register_team_access_observer("memory_goal_folders", on_access_change)
    register_agent_profile_observer("memory_goal_folders", reclassify_agent_documents)


__all__ = ["memory_context_provider", "register_memory"]
