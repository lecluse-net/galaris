"""Terminal Process results remain usable in their originating conversation."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.conversation.models import ConversationProcessLink
from app.conversation.service import (
    admit_message, claim_next_round, claim_next_process_notification,
    deliver_process_notification,
)
from app.file_share import DeliveredResource, ResourceDescriptor
from app.messenger import Message
from app.process import ProcessDefinition, ProcessRun

from .test_service import _scope, _message, _install_messenger


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", [True, False])
@pytest.mark.parametrize("unavailable", [None, "denied", "timeout"])
@pytest.mark.parametrize("typed", [True, False])
async def test_process_outputs_are_named_and_attached_despite_a_summary(
    db, monkeypatch, internal, unavailable, typed,
):
    agent, connection, room = await _scope(db)
    message = await _message(db, connection, room, 1, "Prépare le bilan")
    await admit_message(message, agent_id=agent.id, connection_id=connection.id, language="fr")
    round_ = await claim_next_round("process-output-test")
    definition = ProcessDefinition(agent_id=agent.id, tool_id=connection.tool_id,
        engine_process_id=f"synthetic-{uuid4()}", label="Bilan")
    db.add(definition)
    await db.flush()
    file_uri, document_uri = f"file://{uuid4()}", f"document://{uuid4()}"
    run = ProcessRun(process_id=definition.id, launcher_agent_id=agent.id,
        launch_snapshot={"process_label": "Bilan", "definition": {"graph": {
            "schema_version": "galaris.bpmn/v2"}}},
        engine_code="galaris", correlation_id=str(uuid4()), callback_token=str(uuid4()),
        status="success", input={}, engine_metadata={"native": {"summary": "Bilan prêt."}},
        output={"total": {"type": "int", "value": 0},
            "statut": {"type": "string", "value": "Aucun écart"},
            "valide": {"type": "bool", "value": False},
            "livrables": {"type": "array", "value": [
                {"type": "File", "value": file_uri},
                {"type": "Document", "value": document_uri},
                {"type": "File", "value": file_uri}]}},
    )
    if not typed:
        from app.document.data import unwrap
        run.output = {name: unwrap(value) for name, value in run.output.items()}
        run.launch_snapshot = {"process_label": "Bilan"}
        run.engine_code = "synthetic-external"
    db.add(run)
    await db.flush()
    link = ConversationProcessLink(round_id=round_.id, process_run_id=run.id, action_key="result")
    db.add(link)
    await db.commit()
    sent = []
    _install_messenger(monkeypatch, db, connection, room, sent)
    import app.messenger as messenger_package
    original_messenger = messenger_package.get_messenger

    async def get_messenger(connection_id):
        messenger = await original_messenger(connection_id)
        messenger.kind = "internal" if internal else "telegram"
        return messenger

    monkeypatch.setattr(messenger_package, "get_messenger", get_messenger)

    async def info(context, uri):
        assert context.agent_id == agent.id
        if uri == document_uri and unavailable:
            if unavailable == "denied":
                raise PermissionError("Synthetic access denial")
            await asyncio.Event().wait()
        return ResourceDescriptor(uri=uri, name="bilan.txt" if uri == file_uri else "Analyse")

    async def upload(context, messenger, target, uri):
        descriptor = await info(context, uri)
        assert target == room.id
        return DeliveredResource(source_uri=uri, uri=f"synthetic-chat://room/{uuid4()}",
            name=descriptor.name, media_type="text/plain", size=3)

    metadata = AsyncMock(side_effect=info)
    delivery = AsyncMock(side_effect=upload)
    monkeypatch.setattr("app.file_share.resource_info", metadata)
    monkeypatch.setattr("app.file_share.deliver_resource_to_messenger", delivery)
    if unavailable == "timeout":
        monkeypatch.setattr("app.conversation.process_outputs.PROCESS_OUTPUT_TIMEOUT_SECONDS", 0.05)
    assert await claim_next_process_notification() == link.id
    await deliver_process_notification(link.id)
    await db.refresh(link)
    stored = await db.get(Message, link.notification_message_id)
    assert "Bilan prêt." in stored.text
    assert "total : 0" in stored.text
    assert "statut : Aucun écart" in stored.text
    assert "valide : false" in stored.text
    assert "bilan.txt" in stored.text
    assert '"type"' not in stored.text
    assert len(stored.resource_uris) == (1 if unavailable else 2)
    if internal:
        assert stored.resource_uris == ([file_uri] if unavailable else [file_uri, document_uri])
        assert delivery.await_count == 0
        assert metadata.await_count == 2
    else:
        assert delivery.await_count == 2
    if unavailable:
        assert "Pièce jointe indisponible" in stored.text
        assert document_uri not in stored.resource_uris
    assert link.notification_state == "DELIVERED"
    assert await claim_next_process_notification() is None
    await deliver_process_notification(link.id)
    assert len(sent) == 1


def test_ordinary_json_business_keys_and_typed_empty_values_are_preserved():
    from app.conversation.process_outputs import process_outputs

    plain = process_outputs({"event": {"type": "invoice", "value": 0}}, typed=False)
    assert [(row.label, row.text) for row in plain] == [("event.type", "invoice"), ("event.value", "0")]
    typed = process_outputs({"optional": {"type": "File", "value": None},
        "empty": {"type": "array", "value": []}, "blank": {"type": "string", "value": ""}}, typed=True)
    assert [(row.label, row.text, row.resource_uri) for row in typed] == [
        ("optional", "null", None), ("empty", "[]", None), ("blank", "", None)]
