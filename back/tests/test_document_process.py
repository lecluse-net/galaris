"""Real Process, storage and durable inference; only external provider HTTP is replaced."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.process.document_engine import DocumentEngine, DocumentAdmission
from app.process.models import ProcessDefinition, ProcessRun
from app.process.schemas import EngineRunReference
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
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'galaris'))
    if tool is None:
        tool = ToolModel(code='galaris', label='Galaris', description='', connection_schema={})
        db.add(tool); await db.flush()
    definition = ProcessDefinition(agent_id=agent.id, tool_id=tool.id,
        engine_process_id=f'galaris:{agent.id}:document_analysis', label='Document analysis')
    db.add(definition); await db.flush()
    run = ProcessRun(id=uuid4(), process_id=definition.id, launcher_agent_id=agent.id,
        engine_code='galaris', correlation_id=uuid4().hex, callback_token=uuid4().hex,
        status='running', input=DocumentAdmission(uri=uri, question='Read all sentinels including the final page.',
            model_key=model_key).model_dump())
    db.add(run); await db.commit()
    return run, EngineRunReference(id=run.id, correlation_id=run.correlation_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('count,vision', [(17, True), (500, False)])
async def test_document_process_reopens_completed_batches_without_refactoring_or_rebilling(runtime, tmp_path, monkeypatch, count, vision):
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
    engine = DocumentEngine()
    for _ in range(20):
        snapshot = await engine.get_run(reference)
        if snapshot.status == 'success':
            break
        assert snapshot.status == 'running', snapshot
        await db.refresh(run)
        pending = run.engine_metadata.get('pending_inference')
        if pending:
            from uuid import UUID
            await state(UUID(pending), 'completed')
        # Reconstruct the engine after each step; no in-memory state is required.
        engine = DocumentEngine()
    else:
        pytest.fail('Document process did not finish')
    assert snapshot.output['coverage']['expected_units'] == count
    assert snapshot.output['coverage']['completed_batches'] == snapshot.output['coverage']['expected_batches']
    assert snapshot.output['semantic_accuracy_verified'] is False
    assert any(f'physical page {count}' in str(payload) for payload in requests)
    submitted = len(requests)
    same = await DocumentEngine().get_run(reference)
    assert same.status == 'success' and len(requests) == submitted
    calls = list(await db.scalars(select(LLMCall).where(LLMCall.process_run_id == run.id)))
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
    engine = DocumentEngine()
    assert (await engine.get_run(reference)).status == 'running'
    async with asyncio.timeout(5):
        while not calls:
            await asyncio.sleep(0.02)
    snapshot = await engine.cancel_run(reference)
    assert snapshot.status in {'cancelling', 'cancelled'}
    async with asyncio.timeout(5):
        while (await engine.get_run(reference)).status != 'cancelled':
            await asyncio.sleep(0.02)
    gate.set()
    assert (await engine.get_run(reference)).status == 'cancelled'
    assert len(calls) == 1
    await db.refresh(run)
    assert not run.engine_metadata.get('result')


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
        snapshot = await DocumentEngine().get_run(reference)
        if snapshot.status == 'success':
            break
        await db.refresh(run)
        if run.engine_metadata.get('pending_inference'):
            from uuid import UUID
            await state(UUID(run.engine_metadata['pending_inference']), 'completed')
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
    from app.process import document_engine
    from app.llm import LLM
    monkeypatch.setattr(document_engine.llm_service, 'get_llm', AsyncMock(return_value=LLM(input_image=False)))
    entered = asyncio.Event()
    async def communicate():
        entered.set()
        await asyncio.Future()
    process = SimpleNamespace(pid=123456, returncode=None, communicate=communicate, wait=AsyncMock())
    monkeypatch.setattr(service.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    kill = Mock(); monkeypatch.setattr(os, 'killpg', kill)
    engine = DocumentEngine()
    task = asyncio.create_task(engine.get_run(reference))
    await asyncio.wait_for(entered.wait(), 5)
    snapshot = await engine.cancel_run(reference)
    assert snapshot.status == 'cancelling'
    with pytest.raises(asyncio.CancelledError):
        await task
    kill.assert_called_once()
    process.wait.assert_awaited_once()
    assert (await engine.get_run(reference)).status == 'cancelled'


@pytest.mark.asyncio
async def test_late_document_checkpoint_cannot_rewind_newer_batches_or_change_terminal_result(db, tmp_path, monkeypatch):
    from app.process.interface import engine_checkpoint
    agent, uri = await setup_source(db, tmp_path, monkeypatch, count=2)
    run, _ = await setup_run(db, agent, uri, 1)
    run.engine_metadata = {'completed_batches': 2, 'observations': ['first', 'second']}
    await db.commit()
    late = await engine_checkpoint(run.id, 'galaris', {'completed_batches': 1, 'observations': ['old']},
        expected_values={'completed_batches': 0})
    assert late['applied'] is False
    assert late['metadata']['completed_batches'] == 2 and late['metadata']['observations'] == ['first', 'second']
    run.status = 'cancelled'; await db.commit()
    terminal = await engine_checkpoint(run.id, 'galaris', {'result': {'complete': True}},
        expected_values={'completed_batches': 2})
    assert terminal['applied'] is False and 'result' not in terminal['metadata']
