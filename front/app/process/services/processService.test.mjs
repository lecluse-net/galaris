import assert from 'node:assert/strict'
import test from 'node:test'
import { serviceRecorder } from '../../../test-support/service-recorder.mjs'
import { loadTypescript } from '../../../test-support/load-typescript.mjs'
import { sessionReadCache } from '../../../test-support/session-read-cache.mjs'

test('agent scope reaches definitions, run history, active runs and metrics', async () => {
  const selections = []
  const agentService = loadTypescript(new URL('../../agent/services/agentSelectionService.ts', import.meta.url), {
    '@/core/api': { __esModule: true, default: { get: async (...args) => {
      selections.push(args)
      return { data: [{ id: 7, label: 'Synthetic agent', has_avatar: false }] }
    } }, sessionGeneration: () => 1, AUTH_TOKEN_CHANGED_EVENT: 'auth' },
    '@/core/util/facade': sessionReadCache(),
  })
  const { service, requests } = serviceRecorder(new URL('./processService.ts', import.meta.url), 'processService', { '@/app/agent': agentService })
  assert.deepEqual(await service.agents(), [{ id: 7, label: 'Synthetic agent', has_avatar: false }])
  assert.equal(selections[0][0], '/agents/selection')
  assert.equal(selections[0][1].params.scope, 'management')
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
