"""Real analysis storage and durable inference; only external provider HTTP is replaced."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.llm.document_analysis import DocumentAdmission
from app.llm.document_service import advance_analysis, cancel_analysis
from app.llm.document_contracts import DocumentAnalysisSnapshot
from app.llm.models import LLMDocumentAnalysis
from app.process.models import ProcessDefinition, ProcessRun
from app.llm.facade import read_inference
from app.llm.models import LLMCall
from app.tools import ToolModel
from app.chat.tests.test_native_facade import _scope
from app.messenger import create_internal_room, get_messenger
from app.file_share import ResourceContext, prepared_resource
from core import settings
from tests.test_document_pipeline import pdf
from tests.test_protocol_inference import provider_http
from tests.test_inference_lifecycle import runtime, state


async def setup_source(db, tmp_path, monkeypatch, count=17):
    monkeypatch.setattr(type(settings), 'GALARIS_INTERNAL_MESSENGER_ROOT', str(tmp_path / 'chat'))
    monkeypatch.setattr(type(settings), 'GALARIS_DOCUMENT_ROOT', str(tmp_path / 'documents'))
    agent, owner, _ = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    messenger = await get_messenger(room.connection_id)
    path = tmp_path / 'source.pdf'; pdf(path, count=count)
    message = await messenger.upload_file(room.id, path.read_bytes(), name=path.name)
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
async def test_document_analysis_does_not_create_a_business_process(runtime, tmp_path, monkeypatch):
    from app.llm.profile_models import LlmProfile
    from app.llm.mcp import document_analyze
    from app.tools.mcp_loader import McpToolContext
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
    from app.process import registry
    assert 'galaris' not in registry.codes()
    assert not list(await db.scalars(select(ProcessDefinition).where(ProcessDefinition.agent_id == agent.id)))
    assert not list(await db.scalars(select(ProcessRun).where(ProcessRun.launcher_agent_id == agent.id)))


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
async def test_preparation_cache_does_not_grant_access_by_matching_bytes(db, tmp_path, monkeypatch):
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    async with prepared_resource(ResourceContext(agent.id, 'internal'), uri) as (document, directory):
        manifest = directory / 'manifest.json'
        saved = manifest.stat().st_mtime_ns
        assert document.coverage()['expected_units'] == 2
    async with prepared_resource(ResourceContext(agent.id, 'internal'), uri) as (_, reopened):
        assert reopened == directory and manifest.stat().st_mtime_ns == saved
    stranger, _, _ = await _scope(db)
    with pytest.raises((PermissionError, ValueError)):
        async with prepared_resource(ResourceContext(stranger.id, 'internal'), uri):
            pytest.fail('Cache granted source access to another agent')
    from app.connection import Connection
    connection = await db.scalar(select(Connection).where(Connection.agent_id == agent.id))
    connection.active = False
    await db.commit()
    with pytest.raises((PermissionError, ValueError)):
        async with prepared_resource(ResourceContext(agent.id, 'internal'), uri):
            pytest.fail('Cache ignored revoked connection')


@pytest.mark.asyncio
async def test_cancel_waits_for_inference_stop_and_never_admits_another_batch(runtime, tmp_path, monkeypatch):
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
    snapshot = DocumentAnalysisSnapshot.model_validate(await cancel_analysis(agent.id, reference, runtime='internal'))
    assert snapshot.status in {'cancelling', 'cancelled'}
    async with asyncio.timeout(5):
        while (await advance_analysis(reference)).status != 'cancelled':
            await asyncio.sleep(0.02)
    gate.set()
    assert (await advance_analysis(reference)).status == 'cancelled'
    assert len(calls) == 1
    await db.refresh(run)
    assert not run.checkpoint.get('result')


@pytest.mark.asyncio
async def test_source_change_invalidates_previously_prepared_analysis(db, tmp_path, monkeypatch):
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    async with prepared_resource(ResourceContext(agent.id, 'internal'), uri) as (before, first):
        before_hash = before.sha256
    # A changed source under the same URI must not resolve the previous cache key.
    from app.messenger.models import File
    from uuid import UUID
    attachment = await db.get(File, UUID(uri.rsplit('/', 1)[-1]))
    from core.settings import settings as configuration
    paths = list((tmp_path / 'chat').rglob('*'))
    binary = next(p for p in paths if p.is_file() and p.read_bytes().startswith(b'%PDF-'))
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
    connection = await db.scalar(select(Connection).where(Connection.agent_id == agent.id))
    connection.active = False
    await db.commit()
    with pytest.raises((PermissionError, ValueError)):
        await read_analysis(agent.id, reference, runtime='internal')
    assert (await cancel_analysis(agent.id, reference, runtime='internal'))['status'] == 'success'


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
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'galaris'))
    definition = ProcessDefinition(agent_id=agent.id, tool_id=tool.id,
        engine_process_id=f'galaris:{agent.id}:document_analysis', label='Synthetic legacy analysis',
        deleted_at=datetime.now(timezone.utc) if archived else None)
    business = ProcessDefinition(agent_id=agent.id, tool_id=tool.id,
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
    from app.tools import build_agent_galaris_fastmcp
    from app.tools.authorization import answer_action
    from app.tools.authorization_models import ActionAuthorization
    from core.database import get_db_session
    from uuid import UUID

    db, llm, _, _ = runtime
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    profile = LlmProfile(label='Synthetic approved reader', text_standard_llm_id=llm.id)
    db.add(profile); await db.flush()
    agent.profile_id = profile.id
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'galaris'))
    connection = Connection(agent_id=agent.id, tool_id=tool.id, active=True)
    db.add(connection); await db.commit()
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
