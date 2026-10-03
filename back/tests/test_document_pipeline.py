"""Real document preparation with only provider responses replaced."""

import base64
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.responses import JSONResponse
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.llm.document_input import route_documents
from app.llm import LLM
from core.document import prepare_document
from core.document.worker import prepare


def pdf(path: Path, count: int = 1, size: tuple[int, int] = (200, 100)) -> None:
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    for number in range(1, count + 1):
        page = writer.add_blank_page(width=size[0], height=size[1])
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 8 Tf 10 50 Td (Synthetic report sentinel page {number}: total 1200 units.) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


def body(path: Path, mode: str = 'auto') -> dict:
    return {'model': 'synthetic', 'stream': False, 'max_tokens': 500,
            'galaris_document_mode': mode, 'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': 'What is the total? Cite its page.'},
                {'type': 'file', 'file': {'filename': path.name,
                    'file_data': 'data:application/pdf;base64,' + base64.b64encode(path.read_bytes()).decode()}}]}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, 'rejected', 'document_error', 'other_error', 'empty', 'incomplete', 'unauthorized'])
async def test_native_routing_and_prepared_fallback_preserve_source(tmp_path, failure):
    path = tmp_path / 'source.pdf'; pdf(path)
    requests = []

    async def send(request):
        requests.append(request)
        assert 'galaris_document_mode' not in request
        assert '_galaris_image_path' not in str(request)
        if len(requests) == 1 and failure in {'rejected', 'unauthorized'}:
            return JSONResponse({'error': 'synthetic provider refusal'}, status_code=415 if failure == 'rejected' else 401)
        if len(requests) == 1 and failure in {'document_error', 'other_error'}:
            return JSONResponse({'error': {'message': 'Unsupported PDF file' if failure == 'document_error' else 'Invalid profile'}}, status_code=400)
        content = '' if len(requests) == 1 and failure == 'empty' else json.dumps({'answers': [
            {'id': 'total', 'answer': '1200', 'source': 'page 1',
             'limitations': ['unreadable'] if len(requests) == 1 and failure == 'incomplete' else []}]})
        return JSONResponse({'choices': [{'message': {'content': content}}]})

    response = await route_documents(body(path), LLM(input_file=True, input_image=True), send)
    if failure in {'rejected', 'document_error', 'empty', 'incomplete'}:
        assert len(requests) == 2
        assert response.headers['X-Galaris-Document-Mode'] == 'prepared'
        assert '1200' in str(requests[-1]) and 'physical page 1' in str(requests[-1])
        assert any(part['type'] == 'image_url' for part in requests[-1]['messages'][-1]['content'])
    else:
        assert len(requests) == 1
    assert response.status_code == (401 if failure == 'unauthorized' else 400 if failure == 'other_error' else 200)
    assert response.headers['X-Galaris-Document-Pages'] == '1'
    assert any(p['type'] == 'file' for p in requests[0]['messages'][0]['content'])
    assert any(p['type'] == 'image_url' for p in requests[0]['messages'][0]['content'])
    assert path.exists()


@pytest.mark.asyncio
async def test_text_only_model_receives_all_pages_in_bounded_batches(tmp_path):
    path = tmp_path / 'source.pdf'; pdf(path, count=20)
    from app.llm import document_input
    original = document_input._BATCH_TEXT
    document_input._BATCH_TEXT = 300
    requests = []
    async def send(request):
        requests.append(request)
        return JSONResponse({'choices': [{'message': {'content': 'Source evidence'}}]})
    try:
        response = await route_documents(body(path), LLM(input_file=False, input_image=False), send)
    finally:
        document_input._BATCH_TEXT = original
    assert response.status_code == 200
    assert int(response.headers['X-Galaris-Document-Batches']) > 1
    assert 'page 20' in str(requests)
    assert not any(p.get('type') == 'file' for r in requests for m in r['messages']
                   if isinstance(m['content'], list) for p in m['content'])


def test_five_hundred_page_preparation_preserves_final_page(tmp_path):
    source = tmp_path / 'report.pdf'; pdf(source, count=500)
    result = prepare(source, source.name, 'application/pdf', tmp_path / 'prepared')
    assert len(result['pages']) == 500
    assert 'sentinel page 500' in result['pages'][-1]['text']
    assert (tmp_path / 'prepared' / result['pages'][-1]['image']).is_file()


@pytest.mark.asyncio
async def test_office_conversion_keeps_source_and_pages(tmp_path):
    path = tmp_path / 'synthetic.odt'
    with ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.text')
        archive.writestr('META-INF/manifest.xml', '<?xml version="1.0"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
        archive.writestr('content.xml', '<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:text><text:p>Synthetic office total 1200.</text:p></office:text></office:body></office:document-content>')
    before = path.read_bytes()
    result = await prepare_document(path, path.name, 'application/vnd.oasis.opendocument.text', tmp_path / 'prepared')
    assert result.converted and '1200' in result.text()
    assert result.pages[0].image
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_invalid_file_never_reaches_provider(tmp_path):
    path = tmp_path / 'source.pdf'; pdf(path)
    request = body(path)
    request['messages'][0]['content'][1]['file']['file_data'] = 'data:application/pdf;base64,!!!'
    async def send(_):
        pytest.fail('Invalid document reached provider')
    response = await route_documents(request, LLM(input_file=True), send)
    assert response.status_code == 422
    assert response.headers['X-Galaris-Document-Calls'] == '0'


@pytest.mark.asyncio
async def test_budget_exhaustion_does_not_report_complete_analysis(tmp_path, monkeypatch):
    from app.llm import document_input
    monkeypatch.setattr(document_input, '_BATCH_TEXT', 200)
    path = tmp_path / 'source.pdf'; pdf(path, count=4)
    request = body(path, 'prepared'); request['galaris_document_max_calls'] = 1
    calls = []
    async def send(payload):
        calls.append(payload)
        return JSONResponse({'choices': [{'message': {'content': 'First batch evidence'}}]})
    response = await route_documents(request, LLM(input_file=False), send)
    assert len(calls) == 1
    assert response.status_code == 429
    assert response.headers['X-Galaris-Document-Mode'] == 'prepared-partial'
    assert response.headers['X-Galaris-Document-Calls'] == '1'


@pytest.mark.asyncio
async def test_malformed_provider_batch_is_explicit_failure(tmp_path, monkeypatch):
    from app.llm import document_input
    monkeypatch.setattr(document_input, '_BATCH_TEXT', 200)
    path = tmp_path / 'source.pdf'; pdf(path, count=4)
    async def send(_):
        return JSONResponse({'choices': []})
    response = await route_documents(body(path, 'prepared'), LLM(input_file=False), send)
    assert response.status_code == 502
    assert response.headers['X-Galaris-Document-Mode'] == 'prepared-partial'


@pytest.mark.asyncio
async def test_text_only_harness_prepares_authorized_chat_pdf(db, tmp_path, monkeypatch):
    from app.chat.tests.test_native_facade import _scope
    from app.agent.contracts import TaskMessage
    from app.file_share import ResourceContext
    from app.harness.media import prepare_native_inputs
    from app.messenger import create_internal_room, get_messenger
    from core.settings import settings

    monkeypatch.setattr(type(settings), 'GALARIS_INTERNAL_MESSENGER_ROOT', str(tmp_path))
    monkeypatch.setattr(type(settings), 'GALARIS_DOCUMENT_ROOT', str(tmp_path / 'cache'))
    agent, owner, _ = await _scope(db)
    room = await create_internal_room(actor_user_id=owner.id, agent_id=agent.id)
    messenger = await get_messenger(room.connection_id)
    path = tmp_path / 'source.pdf'; pdf(path)
    message = TaskMessage.from_messenger(await messenger.upload_file(room.id, path.read_bytes(), name='source.pdf'))
    uri = message.attachments[0].uri
    inputs = await prepare_native_inputs(LLM(input_file=False, input_image=False),
        ResourceContext(agent.id, 'internal'), [message], [])
    parts = inputs[uri].parts(uri)
    assert '1200' in str(parts) and 'Page 1' in str(parts) and uri in str(parts)
    assert 'visual coverage incomplete' in str(parts)

    stranger, _, _ = await _scope(db)
    denied = await prepare_native_inputs(LLM(input_file=False),
        ResourceContext(stranger.id, 'internal'), [message], [])
    assert not denied[uri].prepared_parts
    assert 'access denied' in denied[uri].reason


@pytest.mark.asyncio
async def test_sparse_page_detail_crops_preserve_page_and_image_batch_budget(tmp_path):
    path = tmp_path / 'source.pdf'; pdf(path, count=2, size=(500, 600))
    requests = []
    async def send(request):
        requests.append(request)
        return JSONResponse({'choices': [{'message': {'content': 'Synthetic source observations'}}]})
    response = await route_documents(body(path, 'prepared'), LLM(input_image=True), send)
    assert response.status_code == 200
    images_per_call = [sum(part.get('type') == 'image_url' for message in r['messages']
        if isinstance(message['content'], list) for part in message['content']) for r in requests]
    assert sum(images_per_call) == 10
    assert max(images_per_call) <= 8
    assert 'physical page 2' in str(requests) and 'detail quadrant 4' in str(requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('tools', [False, True])
async def test_transient_document_reads_retry_without_replaying_tools(tmp_path, tools):
    path = tmp_path / 'source.pdf'; pdf(path)
    request = body(path, 'prepared')
    if tools:
        request['tools'] = [{'type': 'function', 'function': {'name': 'synthetic_effect'}}]
    requests = []
    async def send(payload):
        requests.append(payload)
        if len(requests) == 1:
            return JSONResponse({'error': {'message': 'Synthetic upstream temporarily unavailable'}}, status_code=503)
        return JSONResponse({'choices': [{'message': {'content': '1200 units on page 1'}}]})
    response = await route_documents(request, LLM(input_image=False), send)
    assert response.status_code == (503 if tools else 200)
    assert len(requests) == (1 if tools else 2)
    if not tools:
        assert requests[0] == requests[1]
    assert response.headers['X-Galaris-Document-Calls'] == str(len(requests))


@pytest.mark.asyncio
async def test_conversion_checkpoint_resumes_only_missing_pages(tmp_path, monkeypatch):
    from core.document import worker
    path = tmp_path / 'source.pdf'; pdf(path, count=4)
    directory = tmp_path / 'prepared'
    import pypdfium2 as pdfium
    render = pdfium.PdfPage.render
    visited = []
    def interrupted(page, *args, **kwargs):
        visited.append(1)
        if len(visited) == 3:
            raise RuntimeError('Synthetic interruption')
        return render(page, *args, **kwargs)
    monkeypatch.setattr(pdfium.PdfPage, 'render', interrupted)
    with pytest.raises(RuntimeError):
        worker.prepare(path, path.name, 'application/pdf', directory)
    saved = json.loads((directory / 'manifest.json').read_text())
    assert saved['completed_pages'] == 2
    monkeypatch.setattr(pdfium.PdfPage, 'render', render)
    prepared = worker.prepare(path, path.name, 'application/pdf', directory)
    assert [page['number'] for page in prepared['pages']] == [1, 2, 3, 4]
    def unexpected(*args, **kwargs):
        raise AssertionError('Completed pages must not be rendered again')
    monkeypatch.setattr(pdfium.PdfPage, 'render', unexpected)
    assert worker.prepare(path, path.name, 'application/pdf', directory) == prepared
    path.write_bytes(b'changed source')
    with pytest.raises(ValueError, match='another source'):
        worker.prepare(path, path.name, 'application/pdf', directory)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['corrupt', 'encrypted'])
async def test_unreadable_files_do_not_call_model(tmp_path, kind):
    path = tmp_path / 'source.pdf'
    if kind == 'encrypted':
        writer = PdfWriter(); writer.add_blank_page(width=200, height=100)
        writer.encrypt('synthetic-password'); writer.write(path)
    else:
        path.write_bytes(b'%PDF-1.7\nBroken synthetic input')
    calls = []
    async def send(request):
        calls.append(request)
        return JSONResponse({})
    response = await route_documents(body(path), LLM(input_file=True), send)
    assert response.status_code == 422 and not calls


@pytest.mark.asyncio
async def test_responses_native_refusal_falls_back_without_changing_protocol(tmp_path):
    from app.llm.document_responses import route_response_documents
    path = tmp_path / 'source.pdf'; pdf(path, count=3)
    calls = []
    async def send(request):
        assert 'messages' not in request
        assert all(part.get('type') != 'file' for item in request['input'] for part in item['content'] if isinstance(item['content'], list))
        calls.append(request)
        if len(calls) == 1:
            return JSONResponse({'error': 'File unsupported'}, status_code=415)
        return JSONResponse({'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '1200 on page 3'}]}]})
    file = body(path)['messages'][0]['content'][1]['file']
    response = await route_response_documents({'model': 'synthetic', 'input': [{'role': 'user', 'content': [{'type': 'input_file', **file}]}]}, LLM(input_file=True), send)
    assert response.status_code == 200 and len(calls) == 2
    assert 'physical page 3' in str(calls[-1])
    assert response.headers['X-Galaris-Document-Coverage'] == 'source-units-supplied'
    assert response.headers['X-Galaris-Document-Semantic-Verified'] == 'false'


def test_spreadsheet_preserves_hidden_sheets_formulas_formats_merges_and_comments(tmp_path):
    from core.document.spreadsheets import spreadsheet_text
    path = tmp_path / 'synthetic.xlsx'
    with ZipFile(path, 'w') as archive:
        archive.writestr('xl/workbook.xml', '<workbook xmlns:r="urn:relations"><sheets><sheet name="Hidden budget" state="hidden" r:id="custom"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="custom" Target="worksheets/custom.xml"/></Relationships>')
        archive.writestr('xl/styles.xml', '<styleSheet><numFmts><numFmt numFmtId="166" formatCode="0.00%"/></numFmts><cellXfs><xf numFmtId="166"/></cellXfs></styleSheet>')
        archive.writestr('xl/worksheets/custom.xml', '<worksheet><sheetData><row r="1" hidden="1"><c r="A1" s="0"><f>SUM(B1:B9)</f><v>0.125</v></c></row></sheetData><mergeCells><mergeCell ref="A1:C1"/></mergeCells></worksheet>')
        archive.writestr('xl/comments1.xml', '<comments><authors><author>Synthetic reviewer</author></authors><commentList><comment ref="A1" authorId="0"><text><t>Not yet approved</t></text></comment></commentList></comments>')
    records = [json.loads(line) for line in spreadsheet_text(path).splitlines()]
    assert any(r.get('sheet') == 'Hidden budget' and r['visibility'] == 'hidden' for r in records)
    cell = next(r for r in records if r.get('cell') == 'A1' and 'formula' in r)
    assert cell['formula'] == 'SUM(B1:B9)' and cell['value'] == '0.125' and cell['number_format'] == '0.00%'
    assert any('A1:C1' in r.get('merged_ranges', []) for r in records)
    assert any(r.get('comment') == 'Not yet approved' for r in records)


@pytest.mark.asyncio
@pytest.mark.parametrize('execution', ['isolated', 'worker'])
async def test_multi_frame_image_inventory_includes_last_frame(tmp_path, execution):
    from PIL import Image
    from core.document import PreparedDocument
    path = tmp_path / 'synthetic.tiff'
    Image.new('RGB', (20, 20), 'white').save(path, save_all=True, append_images=[Image.new('RGB', (20, 20), 'black')])
    if execution == 'worker':
        result = PreparedDocument.model_validate(prepare(path, path.name, 'image/tiff', tmp_path / 'prepared'))
    else:
        result = await prepare_document(path, path.name, 'image/tiff', tmp_path / 'prepared')
    assert len(result.pages) == 2 and result.image_path(result.pages[-1], tmp_path / 'prepared').is_file()
