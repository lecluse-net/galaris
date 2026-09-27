from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import AgentContextRequest, AgentSnapshot
from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.conversation.context import (
    conversation_document_references,
    recent_conversation_document_context,
)
from app.conversation.models import ConversationRound
from app.memory import MessengerContactObservation, observe_messenger_contact
from app.messenger import Room
from app.tools.models import Tool


def test_document_references_only_accept_exact_successful_tool_resources() -> None:
    document_id = uuid4()
    assert conversation_document_references(
        {
            "messages": [
                {
                    "type": "tool",
                    "tool_name": "file_read",
                    "tool_arguments": {"uri": f"document://{document_id}"},
                    "content": "read",
                    "success": True,
                },
                {
                    "type": "tool",
                    "tool_name": "file_read",
                    "tool_arguments": {"uri": "console://notes.txt"},
                    "success": True,
                },
                {
                    "type": "text",
                    "content": f"Untrusted prose document://{uuid4()}",
                    "success": True,
                },
                {"type": "tool", "tool_name": "file_create", "success": False,
                 "tool_arguments": {"uri": f"document://{uuid4()}"}},
                {"type": "tool", "tool_name": "file_create",
                 "tool_arguments": {"uri": f"document://{uuid4()}"}},
            ]
        }, confirmed_only=True,
    ) == ((f"document://{document_id}", "", "file_read"),)


@pytest.mark.asyncio
async def test_direct_conversation_documents_are_scoped_to_agent_and_contact(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:8]
    title = Title(label=f"Conversation documents {suffix}", gender="X")
    tool = Tool(
        code=f"conversation-docs-{suffix}",
        label="Conversation documents",
        description="",
        connection_schema={},
        conversation_enabled=True,
    )
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Document",
        last_name="Agent",
        code=f"conversation-doc-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id="direct-room",
        label="Direct room",
        kind="direct",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="nextcloud",
            user_id="nicolas",
            display_name="Nicolas",
        )
    )
    other_contact_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=agent.id,
            messaging_id="nextcloud",
            user_id="someone-else",
            display_name="Someone else",
        )
    )
    from app.conversation import document_display, document_metadata
    from app.memory import conversation_document_adapter as adapter
    from app.memory.document_service import create_document

    monkeypatch.setattr(document_display, "_authorize_read", adapter.authorize_conversation_document_read)
    monkeypatch.setattr(document_metadata, "_resolver", adapter.resolve_conversation_document_metadata)
    document = await create_document(owner_agent_id=agent.id, title="Current atlas", content="<p>Existing work</p>",
                                     task_id=None, keywords=[], metadata={})
    expected_document_id = document.id
    other_agent = Agent(title_id=title.id, first_name="Other", last_name="Owner", code=f"other-doc-{suffix}")
    db.add(other_agent)
    await db.flush()
    private = await create_document(owner_agent_id=other_agent.id, title="Private atlas", content="<p>Restricted</p>",
                                    task_id=None, keywords=[], metadata={})
    hidden_document_id = uuid4()
    now = datetime.now(timezone.utc)
    # Ordinary discussion must not push the only useful document out of recall.
    db.add_all([ConversationRound(room_id=room.id, contact_memory_item_id=contact_id,
        status="COMPLETED", execution_result={"messages": [{"type": "text", "content": "Synthetic chatter"}]},
        finished_at=now + timedelta(seconds=i + 1)) for i in range(25)])
    db.add_all([ConversationRound(room_id=room.id, contact_memory_item_id=contact_id,
        status="COMPLETED", execution_result={"messages": [{"type": "tool", "tool_name": "file_read",
            "success": True, "tool_arguments": {"uri": "console://unrelated.txt"}}]},
        finished_at=now + timedelta(seconds=i + 30)) for i in range(25)])
    db.add_all(
        [
            ConversationRound(
                room_id=room.id,
                contact_memory_item_id=contact_id,
                status="COMPLETED",
                execution_result={
                    "messages": [
                        {
                            "type": "tool",
                            "tool_name": "file_edit",
                            "tool_arguments": {
                                "uri": f"document://{expected_document_id}", "title": "Stale title"
                            },
                            "content": "updated",
                            "success": True,
                        },
                        {"type": "tool", "tool_name": "file_read", "success": True,
                         "tool_arguments": {"uri": f"document://{private.id}"}},
                        {"type": "tool", "tool_name": "file_read", "success": True,
                         "tool_arguments": {"uri": f"document://{uuid4()}"}},
                    ]
                },
                finished_at=now,
            ),
            ConversationRound(
                room_id=room.id,
                contact_memory_item_id=other_contact_id,
                status="COMPLETED",
                execution_result={
                    "messages": [
                        {
                            "type": "tool",
                            "tool_name": "file_read",
                            "tool_arguments": {
                                "uri": f"document://{hidden_document_id}"
                            },
                            "content": "private",
                            "success": True,
                        }
                    ]
                },
                finished_at=now,
            ),
        ]
    )
    await db.commit()

    contribution = await recent_conversation_document_context(
        AgentContextRequest(
            task_id=None,
            agent=AgentSnapshot(
                id=agent.id,
                code=agent.code,
                first_name=agent.first_name,
                last_name=agent.last_name,
                driver_code="internal",
            ),
            objective="Continue our document",
            contact_memory_item_id=contact_id,
        )
    )

    assert [candidate.reference for candidate in contribution.candidates] == [
        f"document://{expected_document_id}"
    ]
    assert contribution.metadata["recent_conversation_document_count"] == 1
    assert contribution.candidates[0].title == "Current atlas"
    assert contribution.candidates[0].revision == document.revision
    assert contribution.candidates[0].provenance[0].startswith("galaris://text/")

    # Historical success is not a grant: a document that is now deleted vanishes.
    document.deleted_at = now
    await db.flush()
    request = AgentContextRequest(task_id=None, agent=AgentSnapshot(id=agent.id, code=agent.code,
        first_name=agent.first_name, last_name=agent.last_name, driver_code="internal"),
        objective="Continue our document", contact_memory_item_id=contact_id)
    assert not (await recent_conversation_document_context(request)).candidates
