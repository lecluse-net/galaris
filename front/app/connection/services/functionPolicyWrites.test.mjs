import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate } from 'node:timers/promises'
import { deferred, loadTypescript } from '../../../test-support/load-typescript.mjs'

test('queued policy choices cannot execute under a replacement user session', async () => {
  let generation = 'session-one'
  const firstResponse = deferred()
  const requests = []
  class SupersededSessionError extends Error {}
  const { saveFunctionPolicy, waitForFunctionPolicyWrites } = loadTypescript(
    new URL('./connectionService.ts', import.meta.url), {
      '@/core/api': {
        __esModule: true,
        sessionGeneration: () => generation,
        SupersededSessionError,
        default: { put: (url, body, config) => {
          requests.push({ url, body, config })
          return requests.length === 1 ? firstResponse.promise : Promise.resolve({ data: {} })
        } },
      },
      '../events': { CONNECTIONS_CHANGED_EVENT: 'test-connections-changed' },
    },
  )
  const connection = { id: 5, tool_id: 9, agent_id: 7, active: true }
  const capability = { name: 'synthetic_read', capability_kind: 'tool' }
  const first = saveFunctionPolicy(connection, capability, { scope: 'global', state: 'disabled' })
  await setImmediate()
  const second = saveFunctionPolicy(connection, capability, { scope: 'connection', state: 'enabled' })
  const cancelled = assert.rejects(second, SupersededSessionError)
  generation = 'session-two'
  firstResponse.resolve({ data: {} })
  await first
  await cancelled
  await waitForFunctionPolicyWrites(connection.tool_id)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].config._sessionGeneration, 'session-one')

  await saveFunctionPolicy(connection, capability, { scope: 'connection', state: 'ask' })
  assert.equal(requests.length, 2)
  assert.equal(requests[1].body.state, 'ask')
  assert.equal(requests[1].config._sessionGeneration, 'session-two')
})
