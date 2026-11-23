"""Real analysis storage and durable inference; only external provider HTTP is replaced."""

import asyncio
import json
from uuid import uuid4

import httpx
from httpx import AsyncClient
import pytest
from sqlalchemy import select, func

from app.llm.document_analysis import DocumentAdmission
from app.llm.document_service import advance_analysis, cancel_analysis
from app.llm.document_contracts import DocumentAnalysisSnapshot
from app.llm.models import LLMDocumentAnalysis
from app.process.models import ProcessDefinition, ProcessRun
from app.llm.facade import read_inference
from app.llm.models import LLMCall
from app.services import ServiceModel
from app.chat.tests.test_native_facade import _scope
from app.messenger import create_internal_room, get_messenger
from app.file_share import ResourceContext, prepared_resource
from core import settings
from tests.test_document_pipeline import pdf
from tests.test_protocol_inference import provider_http
from tests.test_inference_lifecycle import runtime, state


async def setup_source(db, tmp_path, monkeypatch, count=17, content=None):
    monkeypatch.setattr(type(settings), 'GALARIS_INTERNAL_MESSENGER_ROOT', str(tmp_path / 'chat'))
    agent, owner, _ = await _scope(db)
    from app.connection.facade import get_or_create_connection

    service_id = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "document"))
    await get_or_create_connection(service_id, agent.id, active=True, commit=False)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    messenger = await get_messenger(room.connection_id)
    path = tmp_path / 'source.pdf'; pdf(path, count=count)
    message = await messenger.upload_file(room.id, path.read_bytes() if content is None else content, name=path.name)
    from app.agent.contracts import TaskMessage
    uri = TaskMessage.from_messenger(message).attachments[0].uri
    return agent, uri


async def setup_run(db, agent, uri, model_key):
    run = LLMDocumentAnalysis(id=uuid4(), agent_id=agent.id, status='running',
        input=DocumentAdmission(uri=uri, question='Read all sentinels including the final page.',
            model_key=model_key).model_dump())
    db.add(run); await db.commit()
    return run, run.id


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unchanged", "metadata", "content"])
@pytest.mark.parametrize("consumer", ["advance", "evidence"])
async def test_document_analysis_distinguishes_metadata_edits_from_content_changes(runtime, tmp_path, monkeypatch, change, consumer):
    from app.document import document_service, resource_service as documents
    from app.document.schemas import DocumentUpdate, DocumentPayload
    from app.file_share import resource_info
    from app.task import Task
    from app.llm.facade import acquired_document_evidence

    db, llm, _, _ = runtime
    agent, _uri = await setup_source(db, tmp_path, monkeypatch, count=1)
    document = await document_service.create_document(owner_agent_id=agent.id, title="Synthetic reference",
        content="<p>Synthetic workshop backup schedule: Friday.</p>", task_id=None)
    uri = f"document://{document.id}"
    descriptor = await resource_info(ResourceContext(agent_id=agent.id, runtime="internal"), uri)
    run, reference = await setup_run(db, agent, uri, llm.id)
    task = Task(agent_id=agent.id, label="Synthetic document analysis")
    db.add(task)
    await db.flush()
    run.task_id = task.id
    run.input = {**run.input, "source_version": descriptor.model_dump(
        include={"revision", "etag", "checksum", "modified_at", "size"}, exclude_none=True)}
    if consumer == "evidence":
        run.status = "success"
        run.checkpoint = {"source_passages": [{"locator": "page:1", "text": "Synthetic acquired evidence"}]}
        run.output = {"answer": "The backup check is on Friday.", "coverage": {"complete": True}}
    await db.commit()
    if change != "unchanged":
        update = DocumentUpdate(title="Renamed synthetic reference", expected_lock_version=document.lock_version) if change == "metadata" else (
            DocumentUpdate(payload=DocumentPayload(text="<p>Synthetic new content.</p>"), expected_revision=document.revision))
        await documents.update_item(document.id, update, actor_agent_id=agent.id)
    if consumer == "evidence":
        evidence = await acquired_document_evidence(agent.id, [task.id], [uri])
        assert bool(evidence) == (change != "content")
        return
    result = await advance_analysis(reference)
    if change != "content":
        assert result.status == "running" and result.error is None
    else:
        assert result.status == "error" and result.error.code == "document_source_unavailable"
        assert result.error.phase == "source_version"


@pytest.mark.asyncio
async def test_failed_preparation_keeps_safe_diagnostics_without_rebilling(runtime, tmp_path, monkeypatch):
    db, llm, _, _ = runtime
    private_marker = "Synthetic private input never belongs in an error"
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=1,
        content=b"%PDF-1.7\n" + private_marker.encode())
    run, reference = await setup_run(db, agent, uri, llm.id)
    result = await advance_analysis(reference)
    assert result.status == "error"
    assert result.error.phase == "source_preparation"
    assert result.error.cause_type == "DocumentPreparationError"
    assert result.error.preparation["exception_type"] == "PdfiumError"
    assert result.error.preparation["exit_code"] == 2
    locations = result.error.preparation["locations"]
    assert locations and all("/" not in location and location.rpartition(":")[2].isdigit() for location in locations)
    assert private_marker not in result.model_dump_json()
    assert uri not in result.model_dump_json()
    await db.refresh(run)
    assert run.error == result.error.model_dump()
    assert await advance_analysis(reference) == result
    assert await db.scalar(select(func.count()).select_from(LLMCall)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method,failure", [("HEAD", "404"), ("GET", "503"), ("GET", "timeout")])
async def test_unavailable_https_source_becomes_terminal_without_paid_replay(runtime, tmp_path, monkeypatch, method, failure):
    from app.file_share import web_transport

    db, llm, _, _ = runtime
    agent, _ = await setup_source(db, tmp_path, monkeypatch, count=1)
    uri = "https://files.example.test/synthetic.pdf?token=synthetic-private-token"
    run, reference = await setup_run(db, agent, uri, llm.id)
    requests = []

    async def resolve(value):
        return web_transport._ResolvedHttpsTarget(url=value, hostname="files.example.test",
            host_header="files.example.test", addresses=("1.1.1.1",))

    async def handle(request):
        requests.append(request.method)
        if request.method == method:
            if failure == "timeout":
                raise httpx.ReadTimeout("Synthetic private details must not be persisted", request=request)
            return httpx.Response(int(failure), request=request)
        return httpx.Response(200, headers={"Content-Type": "application/pdf", "Content-Length": "20"})

    monkeypatch.setattr(web_transport, "_resolve_public_https", resolve)
    monkeypatch.setattr(web_transport, "_new_client", lambda: AsyncClient(transport=httpx.MockTransport(handle)))
    result = await advance_analysis(reference)
    assert result.status == "error"
    assert result.error.phase == ("source_access" if method == "HEAD" else "source_preparation")
    assert result.error.cause_type == ("ReadTimeout" if failure == "timeout" else "HTTPStatusError")
    assert result.error.http_status == (None if failure == "timeout" else int(failure))
    assert "synthetic-private-token" not in result.model_dump_json()
    assert "Synthetic private details" not in result.model_dump_json()
    calls = list(requests)
    assert await advance_analysis(reference) == result
    assert requests == calls
    await db.refresh(run)
    assert run.status == "error"
    assert await db.scalar(select(func.count()).select_from(LLMCall)) == 0


@pytest.mark.parametrize("before,after", [
    ({"modified_at": "old", "size": 20}, {"modified_at": "new", "size": 20}),
    ({"revision": 1, "size": 20}, {"revision": 2, "size": 20}),
    ({"checksum": "abc", "size": 20}, {"checksum": "def", "size": 20}),
    ({"revision": 1, "size": 20}, {"size": 20}),
])
def test_source_version_checks_keep_weak_provider_versions_and_real_content_changes(before, after):
    from app.llm.document_contracts import same_source_content_version
    assert not same_source_content_version(before, after)


@pytest.mark.asyncio
async def test_document_analysis_does_not_create_a_business_process(runtime, tmp_path, monkeypatch):
    from app.llm.profile_models import LlmProfile
    from app.llm.mcp import document_analyze
    from app.services.mcp_loader import McpToolContext
    import main  # Assemble the registered application capabilities.

    db, llm, _, _ = runtime
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    profile = LlmProfile(label='Synthetic document reader', text_standard_llm_id=llm.id)
    db.add(profile)
    await db.flush()
    agent.profile_id = profile.id
    await db.commit()
    ctx = McpToolContext(agent_id=agent.id, runtime='internal')
    result = await document_analyze(ctx, uri, 'Read page two', idempotency_key='synthetic-admission')
    duplicate = await document_analyze(ctx, uri, 'Read page two', idempotency_key='synthetic-admission')
    assert duplicate['analysis_id'] == result['analysis_id']
    with pytest.raises(ValueError, match='another request'):
        await document_analyze(ctx, uri, 'A different question', idempotency_key='synthetic-admission')
    # The native BPMN engine now exists independently of document analysis.
    # This admission must still create neither a business definition nor a Run.
    assert not list(await db.scalars(select(ProcessDefinition).where(ProcessDefinition.agent_id == agent.id)))
    assert not list(await db.scalars(select(ProcessRun).where(ProcessRun.launcher_agent_id == agent.id)))


@pytest.mark.asyncio
@pytest.mark.parametrize("lineage", ["direct", "child", "delegated"])
async def test_acquired_document_evidence_is_scoped_and_read_without_repreparing(runtime, tmp_path, monkeypatch, lineage):
    from app.file_share import resource_info
    from app.llm.facade import acquired_document_evidence
    from app.task import Task
    from uuid import UUID

    db, llm, requests, mode = runtime
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    descriptor = await resource_info(ResourceContext(agent_id=agent.id, runtime="internal"), uri)
    task = Task(agent_id=agent.id, label="Synthetic analysis", objective="<p>Read a synthetic source.</p>")
    db.add(task)
    await db.flush()
    root_task = task
    if lineage != "direct":
        root_task = Task(agent_id=agent.id, label="Synthetic analysis coordinator", objective="<p>Coordinate analysis.</p>")
        db.add(root_task)
        await db.flush()
        if lineage == "child":
            task.parent_id = root_task.id
        else:
            task.source_task_id = root_task.id
    run, reference = await setup_run(db, agent, uri, llm.id)
    run.task_id = task.id
    run.input = {**run.input, "source_version": descriptor.model_dump(
        include={"revision", "etag", "checksum", "modified_at", "size"}, exclude_none=True)}
    await db.commit()

    from app.conversation import ConversationRound, ConversationRoundMessage, ConversationTaskLink
    from app.messenger import Attachment, Message, Room
    from app.memory import MessengerContactObservation, observe_messenger_contact
    from app.topic import Topic
    from app.dream.mechanisms.conversation_memory import build_conversation_extraction_input, conversation_memory_mechanism
    from app.dream.service import mark_success
    source_message = await db.scalar(select(Message).join(Attachment, Attachment.message_id == Message.id).where(
        Attachment.file_id == UUID(uri.rsplit("/", 1)[-1])))
    room = await db.get(Room, source_message.messenger_room_id)
    contact = await observe_messenger_contact(MessengerContactObservation(owner_agent_id=agent.id,
        messaging_id="galaris", user_id="synthetic-document-author"))
    topic = Topic(title="Synthetic documentary preferences")
    db.add(topic)
    await db.flush()
    round_ = ConversationRound(room_id=room.id, topic_id=topic.id, contact_memory_item_id=contact, status="SUCCEEDED")
    db.add(round_)
    await db.flush()
    db.add_all([ConversationRoundMessage(round_id=round_.id, message_id=source_message.id, role="input", sequence=1),
        ConversationTaskLink(round_id=round_.id, task_id=root_task.id, action_key="synthetic-document-analysis")])
    await db.commit()
    unanalysed = await build_conversation_extraction_input(round_, topic)
    assert {part.kind for message in unanalysed.current for part in message.evidence} == {"attachment"}
    first_claim = await conversation_memory_mechanism.claim_one()
    assert first_claim is not None
    assert (await conversation_memory_mechanism.prepare(first_claim)).cost == 0
    await mark_success(first_claim, result_count=0)
    assert await conversation_memory_mechanism.count_pending() == 0

    def respond(request):
        return httpx.Response(200, json={"id": "synthetic-evidence", "object": "chat.completion", "created": 1,
            "model": llm.llm_name, "choices": [{"index": 0, "message": {"role": "assistant",
                "content": "The final source page contains 1200 units."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}})
    provider_http(monkeypatch, respond)
    for _ in range(12):
        result = await advance_analysis(reference)
        if result.status == "success":
            break
        assert result.status == "running"
        await db.refresh(run)
        if run.checkpoint.get("pending_inference"):
            await state(UUID(run.checkpoint["pending_inference"]), "completed")
    else:
        pytest.fail("Synthetic document analysis did not complete")

    def no_preparation(*args, **kwargs):
        pytest.fail("Acquired evidence must not download or convert the source again")
    import app.file_share as file_share
    monkeypatch.setattr(file_share, "prepared_resource", no_preparation)
    calls_before = await db.scalar(select(func.count()).select_from(LLMCall))
    evidence = await acquired_document_evidence(agent.id, [task.id], [uri])
    assert len(evidence) == 1
    assert evidence[0].analysis_id == reference
    assert [part["locator"] for part in evidence[0].passages] == ["page:1", "page:2"]
    assert evidence[0].coverage["complete"] is True
    assert evidence[0].coverage["semantic_accuracy_verified"] is False
    assert "1200 units" in evidence[0].answer
    extraction = await build_conversation_extraction_input(round_, topic)
    parts = [part for message in extraction.current for part in message.evidence]
    assert {part.kind for part in parts} == {"attachment", "document_extraction", "document_interpretation"}
    assert {part.locator for part in parts if part.kind == "document_extraction"} == {"page:1", "page:2"}
    assert all(part.uri == uri and part.message_id == source_message.id for part in parts)
    assert await conversation_memory_mechanism.count_pending() == 1
    late_claim = await conversation_memory_mechanism.claim_one()
    assert late_claim is not None and late_claim.subject_id != first_claim.subject_id
    assert await acquired_document_evidence(agent.id, [uuid4()], [uri]) == []
    assert await acquired_document_evidence(agent.id + 10000, [task.id], [uri]) == []
    assert await acquired_document_evidence(agent.id, [task.id], [uri + "x"]) == []
    assert await db.scalar(select(func.count()).select_from(LLMCall)) == calls_before

    run.input = {**run.input, "source_version": {"etag": "obsolete"}}
    await db.commit()
    assert await acquired_document_evidence(agent.id, [task.id], [uri]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('count,vision', [(17, True), (500, False)])
async def test_document_analysis_reopens_completed_batches_without_refactoring_or_rebilling(runtime, tmp_path, monkeypatch, count, vision):
    db, llm, _, _ = runtime
    llm.input_image = vision
    await db.commit()
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count)
    run, reference = await setup_run(db, agent, uri, llm.id)
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': llm.llm_name, 'choices': [{'index': 0, 'message': {'role': 'assistant',
                'content': 'Synthetic evidence: 1200 units; final page visited.'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}})
    provider_http(monkeypatch, respond)
    for _ in range(20):
        snapshot = await advance_analysis(reference)
        if snapshot.status == 'success':
            break
        assert snapshot.status == 'running', snapshot
        await db.refresh(run)
        pending = run.checkpoint.get('pending_inference')
        if pending:
            from uuid import UUID
            await state(UUID(pending), 'completed')
        # Each step reloads the durable state; no in-memory state is required.
    else:
        pytest.fail('Document analysis did not finish')
    assert snapshot.output['coverage']['expected_units'] == count
    assert snapshot.output['coverage']['completed_batches'] == snapshot.output['coverage']['expected_batches']
    assert snapshot.output['semantic_accuracy_verified'] is False
    assert any(f'physical page {count}' in str(payload) for payload in requests)
    submitted = len(requests)
    same = await advance_analysis(reference)
    assert same.status == 'success' and len(requests) == submitted
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.agent_id == agent.id)))
    assert all(call.process_run_id is None and call.purpose == 'document.analysis' for call in calls)
    assert len(calls) == submitted
    assert all(call.status == 'completed' for call in calls)
    assert submitted == snapshot.output['coverage']['expected_batches'] + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_response", [False, True])
async def test_document_reasoning_budget_and_empty_evidence_diagnostics(runtime, tmp_path, monkeypatch, empty_response):
    from uuid import UUID
    from app.llm import LLMProvider
    from app.llm.document_service import read_analysis

    db, llm, _, _ = runtime
    llm.provider = (await db.scalars(select(LLMProvider).where(
        LLMProvider.catalog_code == "openrouter",
    ))).one()
    llm.llm_name = "synthetic/document-reasoner"
    await db.commit()
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    run, reference = await setup_run(db, agent, uri, llm.id)
    requests = []

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{
                "id": llm.llm_name, "context_length": 131072,
                "top_provider": {"max_completion_tokens": 16384},
            }]})
        payload = json.loads(request.content)
        requests.append(payload)
        enough = payload.get("max_tokens", 512) >= 16384 and not empty_response
        return httpx.Response(200, json={"id": "synthetic-document-capacity", "object": "chat.completion",
            "created": 1, "model": llm.llm_name, "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "Synthetic page two evidence." if enough else ""},
                "finish_reason": "stop" if enough else "length"}]})

    provider_http(monkeypatch, respond)
    for _ in range(10):
        result = await advance_analysis(reference)
        if result.status != "running":
            break
        await db.refresh(run)
        if run.checkpoint.get("pending_inference"):
            await state(UUID(run.checkpoint["pending_inference"]), "completed")
    if empty_response:
        assert result.status == "error"
        assert result.error.code == "document_inference_empty"
        assert result.output["coverage"]["completed_batches"] == 0
    else:
        assert result.status == "success", result
        assert result.output["answer"] == "Synthetic page two evidence."
    snapshot = await read_analysis(agent.id, reference, runtime="internal")
    assert snapshot["status"] == result.status
    submitted = len(requests)
    assert await advance_analysis(reference) == result
    assert len(requests) == submitted  # Reading/reopening never replays a paid batch.


@pytest.mark.asyncio
async def test_temporary_cache_reuses_preparation_and_rechecks_source_access(db, tmp_path, monkeypatch):
    from pathlib import Path
    from tempfile import gettempdir

    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    async with prepared_resource(ResourceContext(agent.id, 'internal'), uri) as (document, directory):
        assert directory.is_relative_to(Path(gettempdir()))
        manifest = directory / 'manifest.json'
        saved = manifest.stat().st_mtime_ns
        assert document.coverage()['expected_units'] == 2
    async with prepared_resource(ResourceContext(agent.id, 'internal'), uri) as (_, reopened):
        assert reopened == directory and manifest.stat().st_mtime_ns == saved
    # A reader upgrade uses a separate workspace, rather than reusing stale evidence
    # or failing against a checkpoint from the previous preparation contract.
    from app.file_share import document_facade
    original_prepare = document_facade.prepare_document
    async def upgraded_prepare(path, name, media_type, destination):
        assert destination != directory
        return await original_prepare(path, name, media_type, destination)
    with monkeypatch.context() as patch:
        patch.setattr(document_facade, 'preparation_version', lambda name: 4)
        patch.setattr(document_facade, 'prepare_document', upgraded_prepare)
        async with prepared_resource(ResourceContext(agent.id, 'internal'), uri) as (_, upgraded):
            assert upgraded != directory
    stranger, _, _ = await _scope(db)
    with pytest.raises((PermissionError, ValueError)):
        async with prepared_resource(ResourceContext(stranger.id, 'internal'), uri):
            pytest.fail('Preparation granted source access to another agent')
    from app.connection import Connection
    connection = await db.scalar(select(Connection).join(ServiceModel).where(
        Connection.agent_id == agent.id, ServiceModel.code == "chat",
    ))
    connection.active = False
    await db.commit()
    with pytest.raises((PermissionError, ValueError)):
        async with prepared_resource(ResourceContext(agent.id, 'internal'), uri):
            pytest.fail('Preparation ignored revoked connection')


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["cancel", "source_unavailable", "source_unavailable_after_completion"])
async def test_cancel_waits_for_inference_stop_and_never_admits_another_batch(runtime, tmp_path, monkeypatch, trigger):
    db, llm, _, _ = runtime
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    run, reference = await setup_run(db, agent, uri, llm.id)
    gate = asyncio.Event()
    calls = []
    async def respond(request):
        calls.append(json.loads(request.content))
        await gate.wait()
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': llm.llm_name, 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'late answer'}, 'finish_reason': 'stop'}]})
    provider_http(monkeypatch, respond)
    assert (await advance_analysis(reference)).status == 'running'
    async with asyncio.timeout(5):
        while not calls:
            await asyncio.sleep(0.02)
    if trigger == "cancel":
        snapshot = DocumentAnalysisSnapshot.model_validate(await cancel_analysis(agent.id, reference, runtime='internal'))
        assert snapshot.status in {'cancelling', 'cancelled'}
        async with asyncio.timeout(5):
            while (await advance_analysis(reference)).status != 'cancelled':
                await asyncio.sleep(0.02)
        terminal = "cancelled"
    else:
        from app.connection import Connection
        from uuid import UUID

        await db.refresh(run)
        pending = UUID(run.checkpoint["pending_inference"])
        if trigger == "source_unavailable_after_completion":
            gate.set()
            await state(pending, "completed")
        connection = await db.scalar(select(Connection).join(ServiceModel).where(
            Connection.agent_id == agent.id, ServiceModel.code == "chat",
        ))
        connection.active = False
        await db.commit()
        snapshot = await advance_analysis(reference)
        assert snapshot.status == "error" and snapshot.error.phase == "source_access"
        await state(pending, "completed" if trigger == "source_unavailable_after_completion" else "stopped")
        terminal = "error"
    gate.set()
    assert (await advance_analysis(reference)).status == terminal
    assert len(calls) == 1
    await db.refresh(run)
    assert not run.checkpoint.get('result')


@pytest.mark.asyncio
async def test_source_change_invalidates_previously_prepared_analysis(db, tmp_path, monkeypatch):
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    async with prepared_resource(ResourceContext(agent.id, 'internal'), uri) as (before, first):
        before_hash = before.sha256
    # A changed source under the same URI must be prepared from its current bytes.
    from app.messenger.models import File
    from uuid import UUID
    attachment = await db.get(File, UUID(uri.rsplit('/', 1)[-1]))
    from core.storage import file_path
    binary = file_path(attachment.id)
    pdf(binary, count=3)
    async with prepared_resource(ResourceContext(agent.id, 'internal'), uri) as (after, second):
        assert after.sha256 != before_hash and second != first
        assert after.coverage()['expected_units'] == 3


@pytest.mark.asyncio
async def test_text_model_gets_sourced_observations_from_profile_vision_reader(runtime, tmp_path, monkeypatch):
    from app.llm.provider_models import LLM
    db, llm, _, _ = runtime
    vision = LLM(llm_provider_id=llm.llm_provider_id, code='synthetic-vision-' + uuid4().hex,
        label='Synthetic visual reader', llm_name='synthetic-vision-deployment', input_image=True)
    db.add(vision); await db.commit()
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    run, reference = await setup_run(db, agent, uri, llm.id)
    run.input = {**run.input, 'vision_model_key': vision.id}
    await db.commit()
    requests = []
    def respond(request):
        payload = json.loads(request.content); requests.append(payload)
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': payload['model'], 'choices': [{'index': 0, 'message': {'role': 'assistant',
                'content': 'Synthetic sourced visual observations on page 2'}, 'finish_reason': 'stop'}]})
    provider_http(monkeypatch, respond)
    for _ in range(8):
        snapshot = await advance_analysis(reference)
        if snapshot.status == 'success':
            break
        await db.refresh(run)
        if run.checkpoint.get('pending_inference'):
            from uuid import UUID
            await state(UUID(run.checkpoint['pending_inference']), 'completed')
    assert snapshot.status == 'success'
    assert requests[0]['model'] == vision.llm_name
    assert 'image_url' in str(requests[0])
    assert requests[-1]['model'] == llm.llm_name
    assert 'Synthetic sourced visual observations on page 2' in str(requests[-1])
    assert 'image_url' not in str(requests[-1])
    assert snapshot.output['coverage']['visual_model_key'] == vision.id


@pytest.mark.asyncio
async def test_cancelling_during_conversion_kills_local_worker(db, tmp_path, monkeypatch):
    from core.document import service
    from unittest.mock import AsyncMock, Mock
    from types import SimpleNamespace
    import os
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    run, reference = await setup_run(db, agent, uri, 1)
    from app.llm import document_analysis
    from app.llm import LLM
    monkeypatch.setattr(document_analysis.llm_service, 'get_llm', AsyncMock(return_value=LLM(input_image=False)))
    entered = asyncio.Event()
    async def communicate():
        entered.set()
        await asyncio.Future()
    process = SimpleNamespace(pid=123456, returncode=None, communicate=communicate, wait=AsyncMock())
    monkeypatch.setattr(service.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    kill = Mock(); monkeypatch.setattr(os, 'killpg', kill)
    task = asyncio.create_task(advance_analysis(reference))
    await asyncio.wait_for(entered.wait(), 5)
    snapshot = DocumentAnalysisSnapshot.model_validate(await cancel_analysis(agent.id, reference, runtime='internal'))
    assert snapshot.status == 'cancelling'
    with pytest.raises(asyncio.CancelledError):
        await task
    kill.assert_called_once()
    process.wait.assert_awaited_once()
    assert (await advance_analysis(reference)).status == 'cancelled'


@pytest.mark.asyncio
async def test_late_document_checkpoint_cannot_rewind_newer_batches_or_change_terminal_result(db, tmp_path, monkeypatch):
    from app.llm.document_store import document_checkpoint
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    run, _ = await setup_run(db, agent, uri, 1)
    run.checkpoint = {'completed_batches': 2, 'observations': ['first', 'second']}
    await db.commit()
    late = await document_checkpoint(run.id, {'completed_batches': 1, 'observations': ['old']},
        expected_values={'completed_batches': 0})
    assert late['applied'] is False
    assert late['metadata']['completed_batches'] == 2 and late['metadata']['observations'] == ['first', 'second']
    run.status = 'cancelled'; await db.commit()
    terminal = await document_checkpoint(run.id, {'result': {'complete': True}},
        expected_values={'completed_batches': 2})
    assert terminal['applied'] is False and 'result' not in terminal['metadata']


@pytest.mark.asyncio
async def test_scheduler_progresses_analysis_without_polling_and_enforces_ownership(runtime, tmp_path, monkeypatch):
    from app.llm.document_service import analysis_tick, read_analysis
    from datetime import datetime, timedelta, timezone

    db, llm, _, _ = runtime
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    run, reference = await setup_run(db, agent, uri, llm.id)
    provider_http(monkeypatch, lambda request: httpx.Response(200, json={
        'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
        'model': llm.llm_name, 'choices': [{'index': 0, 'message': {
            'role': 'assistant', 'content': 'Synthetic page two evidence'}, 'finish_reason': 'stop'}]}))
    # A live lease excludes another scheduler root; expired work is recoverable.
    run.lease_token = uuid4()
    run.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
    await db.commit()
    await analysis_tick()
    await db.refresh(run)
    assert not run.checkpoint.get('pending_inference')
    run.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    for _ in range(8):
        await analysis_tick()
        await db.refresh(run)
        if run.status == 'success':
            break
        if run.checkpoint.get('pending_inference'):
            from uuid import UUID
            await state(UUID(run.checkpoint['pending_inference']), 'completed')
    assert run.status == 'success'
    assert (await read_analysis(agent.id, reference, runtime='internal'))['output']['answer'] == 'Synthetic page two evidence'
    stranger, _, _ = await _scope(db)
    with pytest.raises(PermissionError):
        await read_analysis(stranger.id, reference, runtime='internal')
    with pytest.raises(PermissionError):
        await cancel_analysis(stranger.id, reference, runtime='internal')
    # Revoking source access hides even a completed answer, while its owner can stop work.
    from app.connection import Connection
    connection = await db.scalar(select(Connection).join(ServiceModel).where(
        Connection.agent_id == agent.id, ServiceModel.code == "chat",
    ))
    connection.active = False
    await db.commit()
    with pytest.raises((PermissionError, ValueError)):
        await read_analysis(agent.id, reference, runtime='internal')
    assert (await cancel_analysis(agent.id, reference, runtime='internal'))['status'] == 'success'


@pytest.mark.asyncio
async def test_document_analysis_delegation_requires_scope_and_source_access(runtime, tmp_path, monkeypatch):
    from app.connection.facade import get_or_create_connection, set_management_scope
    from app.document import document_service, item_sharing, resource_service
    from app.llm.mcp import document_analysis_cancel, document_analysis_get
    from app.services import McpToolContext

    db, llm, _, _ = runtime
    owner, _ = await setup_source(db, tmp_path, monkeypatch, count=1)
    peer, _, _ = await _scope(db)
    service_id = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "document"))
    connection = await get_or_create_connection(service_id, peer.id)
    document = await document_service.create_document(owner_agent_id=owner.id, title="Synthetic report",
        content="<p>Synthetic report content.</p>", task_id=None)
    _, reference = await setup_run(db, owner, f"document://{document.id}", llm.id)
    ctx = McpToolContext(agent_id=peer.id, runtime="internal")
    await set_management_scope(connection.id, "all", authorized=True)
    with pytest.raises(resource_service.DocumentPermissionError):
        await document_analysis_get(ctx, str(reference))
    await item_sharing.update_agent_sharing(document.id, agent_id=owner.id, kind="agent",
        target_id=peer.id, access="read")
    assert (await document_analysis_get(ctx, str(reference)))["analysis_id"] == str(reference)
    await set_management_scope(connection.id, None, authorized=True)
    with pytest.raises(PermissionError):
        await document_analysis_cancel(ctx, str(reference))
    await set_management_scope(connection.id, "all", authorized=True)
    assert (await document_analysis_cancel(ctx, str(reference)))["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize('archived', [False, True])
async def test_dbadmin_moves_legacy_analyses_without_rebilling_and_keeps_business_processes(runtime, tmp_path, monkeypatch, archived):
    from sqlalchemy import delete
    from app.llm.models import LLMInference
    from app.process.dbadmin import _move_document_analyses
    from datetime import datetime, timezone

    db, llm, _, _ = runtime
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    run, reference = await setup_run(db, agent, uri, llm.id)
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': llm.llm_name, 'choices': [{'index': 0, 'message': {
                'role': 'assistant', 'content': 'Synthetic paid source evidence'}, 'finish_reason': 'stop'}]})
    provider_http(monkeypatch, respond)
    await advance_analysis(reference)
    await db.refresh(run)
    from uuid import UUID
    pending = UUID(run.checkpoint['pending_inference'])
    await state(pending, 'completed')
    assert len(requests) == 1
    # Represent the previous persisted contract, using entirely synthetic source data.
    input_data, checkpoint = dict(run.input), dict(run.checkpoint)
    await db.execute(delete(LLMDocumentAnalysis).where(LLMDocumentAnalysis.id == reference))
    tool = await db.scalar(select(ServiceModel).where(ServiceModel.code == 'galaris'))
    definition = ProcessDefinition(agent_id=agent.id, service_id=tool.id,
        engine_process_id=f'galaris:{agent.id}:document_analysis', label='Synthetic legacy analysis',
        deleted_at=datetime.now(timezone.utc) if archived else None)
    business = ProcessDefinition(agent_id=agent.id, service_id=tool.id,
        engine_process_id='synthetic-business-workflow', label='Synthetic business workflow')
    db.add_all([definition, business]); await db.flush()
    legacy = ProcessRun(id=reference, process_id=definition.id, launcher_agent_id=agent.id,
        status='running', engine_code='galaris', engine_run_id=str(reference),
        correlation_id=uuid4().hex, callback_token=uuid4().hex,
        input=input_data, engine_metadata=checkpoint,
        deleted_at=datetime.now(timezone.utc) if archived else None)
    db.add(legacy); await db.flush()
    inference = await db.get(LLMInference, pending)
    inference.request = {**inference.request, 'process_run_id': str(reference), 'purpose': 'process.exec'}
    call = await db.scalar(select(LLMCall).where(LLMCall.agent_id == agent.id))
    call.process_run_id = reference
    call.purpose = 'process.exec'
    await db.commit()
    business_id, definition_id = business.id, definition.id
    await _move_document_analyses(db)
    await db.commit()
    await _move_document_analyses(db)
    await db.commit()
    assert await db.get(ProcessDefinition, business_id) is not None
    assert await db.scalar(select(ProcessDefinition.id).where(ProcessDefinition.id == definition_id)
        .execution_options(include_historized=True)) is None
    assert await db.scalar(select(ProcessRun.id).where(ProcessRun.id == reference)
        .execution_options(include_historized=True)) is None
    await db.refresh(call)
    assert call.process_run_id is None and call.purpose == 'document.analysis'
    moved = await db.get(LLMDocumentAnalysis, reference)
    assert moved.checkpoint == checkpoint
    for _ in range(8):
        snapshot = await advance_analysis(reference)
        if snapshot.status == 'success':
            break
        await db.refresh(moved)
        await state(UUID(moved.checkpoint['pending_inference']), 'completed')
    assert snapshot.status == 'success'
    assert len(requests) == snapshot.output['coverage']['expected_batches'] + 1


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario', ['success', 'revoked', 'cancelled_before_dispatch'])
async def test_document_worker_uses_the_real_mcp_agreement(runtime, tmp_path, monkeypatch, scenario):
    from fastmcp import Client
    from app.connection import Connection
    from app.llm.profile_models import LlmProfile
    from app.llm.document_service import analysis_tick
    from app.services import build_agent_galaris_fastmcp
    from app.services.authorization import answer_action
    from app.services.authorization_models import ActionAuthorization
    from core.database import get_db_session
    from core.authorize.models import Assignment, Privilege, Role
    from uuid import UUID

    db, llm, _, _ = runtime
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    privilege = await db.scalar(select(Privilege).where(Privilege.code == 'PERMISSION_DECIDE'))
    assert privilege is not None
    role = Role(code=f'synthetic-document-approver-{uuid4().hex}', privileges=[privilege])
    db.add(role)
    await db.flush()
    db.add(Assignment(user_id=agent.user_id, role_id=role.id))
    profile = LlmProfile(label='Synthetic approved reader', text_standard_llm_id=llm.id)
    db.add(profile); await db.flush()
    agent.profile_id = profile.id
    connection = await db.scalar(select(Connection).join(ServiceModel).where(
        Connection.agent_id == agent.id, ServiceModel.code == "document",
    ))
    assert connection is not None
    await db.commit()
    server = await build_agent_galaris_fastmcp(agent.id, allowed_tool_names={'document_analyze'})
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': llm.llm_name, 'choices': [{'index': 0, 'message': {
                'role': 'assistant', 'content': 'Synthetic approved evidence'}, 'finish_reason': 'stop'}]})
    provider_http(monkeypatch, respond)
    async with Client(server) as client:
        arguments = {'uri': uri, 'question': 'Read the second synthetic page'}
        pending = await client.call_tool('document_analyze', arguments, raise_on_error=False)
        control = pending.meta['galaris.authorization/v1']
        permit = UUID(control['request_id'])
        assert not list(await db.scalars(select(LLMDocumentAnalysis).where(LLMDocumentAnalysis.agent_id == agent.id)))
        async with get_db_session() as writer:
            authorization = await writer.get(ActionAuthorization, permit)
            assert await answer_action(permit, user_id=authorization.approver_user_id, approved=True)
        admitted = await client.call_tool('document_analyze', arguments, raise_on_error=False,
            meta={'galaris.authorization/v1': {'continuation': control['continuation']}})
        assert not admitted.is_error, admitted
    run = await db.scalar(select(LLMDocumentAnalysis).where(LLMDocumentAnalysis.agent_id == agent.id))
    assert run.dispatch['authorization_permit'] == str(permit)
    if scenario == 'revoked':
        connection.active = False
        await db.commit()
    elif scenario == 'cancelled_before_dispatch':
        assert (await cancel_analysis(agent.id, run.id, runtime='internal'))['status'] == 'cancelled'
    for _ in range(8):
        await analysis_tick()
        await db.refresh(run)
        if run.status in {'success', 'error', 'cancelled'}:
            break
        if run.checkpoint.get('pending_inference'):
            await state(UUID(run.checkpoint['pending_inference']), 'completed')
    authorization = await db.get(ActionAuthorization, permit, populate_existing=True)
    if scenario == 'success':
        assert run.status == 'success' and authorization.status == 'completed'
        assert len(requests) == run.output['coverage']['expected_batches'] + 1
    else:
        assert run.status == ('error' if scenario == 'revoked' else 'cancelled')
        assert authorization.status in {'failed', 'invalidated'}
        assert not requests
    assert run.authorization_settled is True
