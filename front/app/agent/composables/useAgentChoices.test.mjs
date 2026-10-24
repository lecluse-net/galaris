import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../../test-support/load-typescript.mjs'

test('domain choices reject late metadata after a role change and clear a current denial', async () => {
  let generation = 1
  const window = new EventTarget()
  const reads = []
  const read = () => { const request = deferred(); reads.push(request); return request.promise }
  const { useAgentChoices } = loadTypescript(new URL('./useAgentChoices.ts', import.meta.url), {
    vue,
    axios: { isAxiosError: error => error?.isAxiosError === true },
    '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', sessionGeneration: () => generation },
    '../services/agentSelectionService': { getAgentSelection: read },
  }, { window })
  const scope = vue.effectScope()
  const choices = scope.run(useAgentChoices)
  const first = choices.fetchAgents()
  generation++
  window.dispatchEvent(new Event('auth'))
  reads[0].resolve([{ id: 1, label: 'Previous role', has_avatar: false }])
  await first
  assert.deepEqual(choices.agents, [])
  const second = choices.fetchAgents()
  reads[1].resolve([{ id: 2, label: 'Synthetic agent', has_avatar: false }])
  await second
  assert.deepEqual(choices.agents.map(agent => agent.id), [2])
  const denied = choices.fetchAgents()
  reads[2].reject({ isAxiosError: true, response: { status: 403 } })
  await assert.rejects(denied)
  assert.deepEqual(choices.agents, [])
  const disposed = choices.fetchAgents()
  scope.stop()
  reads[3].resolve([{ id: 3, label: 'Obsolete view', has_avatar: false }])
  await disposed
  assert.deepEqual(choices.agents, [])
})
