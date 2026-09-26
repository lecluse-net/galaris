import assert from 'node:assert/strict'
import test from 'node:test'
import { serviceRecorder } from '../../../test-support/service-recorder.mjs'

function setup() { return serviceRecorder(new URL('./chatService.ts', import.meta.url), 'chatService', { axios: { isAxiosError: () => false } }) }

test('voice callbacks retained across a development reload can still send ICE candidates', async () => {
  const { service, requests } = setup()
  const candidate = { candidate: 'candidate:1 1 udp 1 192.0.2.10 50000 typ host', sdp_mid: '0', sdp_m_line_index: 0 }
  const end = { candidate: null, sdp_mid: null, sdp_m_line_index: null }
  // A retained callback may use the old method with either version of the sender.
  await service.addCallCandidate('room-a', 'call/a', candidate)
  await service.addCallCandidate('room-a', 'call/a', [candidate, end])
  await service.addCallCandidates('room-a', 'call/a', [candidate, end])

  assert.deepEqual(requests.map(request => request.args), [
    ['/chat/rooms/room-a/calls/call%2Fa/candidates', { candidates: [candidate] }],
    ['/chat/rooms/room-a/calls/call%2Fa/candidates', { candidates: [candidate, end] }],
    ['/chat/rooms/room-a/calls/call%2Fa/candidates', { candidates: [candidate, end] }],
  ])
})

test('room creation sends identity, title, topic and preview preference atomically', async () => {
  const { service, requests, response } = setup()
  assert.equal(await service.createRoom(7, 'Private', 'topic-a', false), response)
  assert.deepEqual(requests, [{ method: 'post', args: ['/chat/rooms', { agent_id: 7, label: 'Private', topic_id: 'topic-a', show_last_message: false }] }])
})

test('archive and external filters are independent and archiving sends the requested boolean', async () => {
  const { service, requests } = setup()
  await service.rooms(2, 500, 'report', 7, false, true)
  assert.deepEqual(requests.pop(), { method: 'get', args: ['/chat/rooms', { params: { page: 2, page_size: 500, search: 'report', agent_id: 7, include_external: false, include_archived: true } }] })
  for (const archived of [true, false]) {
    await service.setArchived('room-a', archived)
    assert.deepEqual(requests.pop(), { method: 'patch', args: ['/chat/rooms/room-a/archive', { archived }] })
  }
})

test('text and attachment messages preserve task intent, effort and idempotency identity', async () => {
  const { service, requests } = setup()
  await service.send('room-a', '@effort Solve', 'reply-a', 'topic-a', 'client-a', 'max', true, null, 'fr')
  assert.deepEqual(requests.pop(), { method: 'post', args: ['/chat/rooms/room-a/messages', { client_message_id: 'client-a', text: '@effort Solve', language: 'fr', topic_id: 'topic-a', reply_to_message_id: 'reply-a', reasoning_effort_override: 'max', task_requested: true }] })
  await service.upload('room-a', [new File(['example'], 'example.txt')], 'Solve', 'reply-a', 'topic-a', 'client-b', 'high', true, null, 'fr')
  const { args: [url, form] } = requests.pop()
  assert.equal(url, '/chat/rooms/room-a/attachments')
  assert.deepEqual(Object.fromEntries([...form.entries()].filter(([key]) => key !== 'files')), {
    client_message_id: 'client-b', text: 'Solve', language: 'fr', topic_id: 'topic-a', reply_to_message_id: 'reply-a', reasoning_effort_override: 'high', task_requested: 'true',
  })
  assert.equal(form.get('files').name, 'example.txt')
  assert.equal(await form.get('files').text(), 'example')
})

test('displayed document context is optional for both text and attachment messages', async () => {
  const { service, requests } = setup()
  const focus = { revision: 3, surface: 'rendered', selection: { start: 0, end: 4, text: 'Look', truncated: false }, cursor: { offset: 4, before: 'Look', after: ' here' }, viewport: null }
  for (const documentId of ['doc-a', null]) {
    await service.send('room-a', 'Look here', null, null, 'client-a', null, false, documentId, 'en', focus)
    const body = requests.pop().args[1]
    assert.equal(body.displayed_document_id, documentId ?? undefined)
    assert.equal(body.text, 'Look here')
    assert.deepEqual(body.document_focus, documentId ? focus : undefined)
    await service.upload('room-a', [new File(['example'], 'example.txt')], 'Look here', null, null, 'client-b', null, false, documentId, 'en', focus)
    const form = requests.pop().args[1]
    assert.equal(form.get('displayed_document_id'), documentId)
    assert.equal(form.get('text'), 'Look here')
    assert.equal(form.get('document_focus'), documentId ? JSON.stringify(focus) : null)
  }
})

test('text and attachment messages carry the language chosen by their author', async () => {
  const { service, requests } = setup()
  for (const language of ['fr', 'en', 'zh']) {
    await service.send('room-a', '1', null, null, 'client-a', null, false, null, language)
    assert.equal(requests.pop().args[1].language, language)
    await service.upload('room-a', [], '1', null, null, 'client-b', null, false, null, language)
    assert.equal(requests.pop().args[1].get('language'), language)
  }
})
