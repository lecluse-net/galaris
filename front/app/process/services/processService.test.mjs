import assert from 'node:assert/strict'
import test from 'node:test'
import { serviceRecorder } from '../../../test-support/service-recorder.mjs'

test('agent scope reaches definitions, run history, active runs and metrics', async () => {
  const { service, requests } = serviceRecorder(new URL('./processService.ts', import.meta.url), 'processService')
  await service.definitions(7)
  await service.operations(7)
  await service.runs({ agentId: 7, page: 2, pageSize: 500 })
  await service.runs({ agentId: 7, active: true })
  assert.equal(requests.length, 4)
  assert.ok(requests.every(request => request.args[1].params.agent_id === 7))
  assert.equal(requests[2].args[1].params.page, 2)
  assert.equal(requests[2].args[1].params.page_size, 500)
  assert.equal(requests[3].args[1].params.active, true)
})
