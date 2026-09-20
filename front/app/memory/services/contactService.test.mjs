import assert from 'node:assert/strict'
import test from 'node:test'
import { serviceRecorder } from '../../../test-support/service-recorder.mjs'

test('contact pagination stays scoped and merge never swaps source and canonical target', async () => {
  const { service, requests, response } = serviceRecorder(new URL('./contactService.ts', import.meta.url), 'contactService')
  await service.list({ agentId: 7 })
  assert.deepEqual(requests.pop(), { method: 'get', args: ['/contacts', { params: { agent_id: 7, q: '', limit: 50, offset: 0 } }] })
  assert.equal(await service.merge('source/a', 'canonical-b'), response)
  assert.deepEqual(requests.pop(), { method: 'post', args: ['/contacts/source%2Fa/merge', { target_contact_item_id: 'canonical-b' }] })
  assert.equal(await service.forget('source/a'), response)
  assert.deepEqual(requests.pop(), { method: 'delete', args: ['/contacts/source%2Fa'] })
})
