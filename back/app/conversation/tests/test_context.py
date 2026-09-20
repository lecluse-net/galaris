from __future__ import annotations

from datetime import datetime, timezone
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
            ]
        }
    ) == ((f"document://{document_id}", "", "file_read"),)


@pytest.mark.asyncio
async def test_direct_conversation_documents_are_scoped_to_agent_and_contact(
    db: AsyncSession,
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
    expected_document_id = uuid4()
    hidden_document_id = uuid4()
    now = datetime.now(timezone.utc)
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
                                "uri": f"document://{expected_document_id}"
                            },
                            "content": "updated",
                            "success": True,
                        }
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
