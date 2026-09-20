import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'

function setup() {
  let generation = 'one'
  const requests = []
  const titleLabels = loadTypescript(new URL('./titleLabels.ts', import.meta.url), {})
  const { useAgentStore } = loadTypescript(new URL('./stores/agentStore.ts', import.meta.url), {
    pinia,
    '@/core/api': { sessionGeneration: () => generation },
    '../titleLabels': titleLabels,
    '../services/agentService': { agentService: {
      getAgents() { const pending = deferred(); requests.push(pending); return pending.promise },
    } },
  })
  const store = useAgentStore(pinia.createPinia())
  return { store, requests, switchSession: () => { generation = 'two' }, close: () => store.$dispose() }
}

test('simultaneous page and widget loads share one agents request and all await its data', async () => {
  const state = setup()
  try {
    const loads = Array.from({ length: 30 }, () => state.store.fetchAgents())
    assert.equal(state.requests.length, 1)
    state.requests[0].resolve({ data: [{ id: 1 }] })
    await Promise.all(loads)
    assert.deepEqual(state.store.agents.map(agent => agent.id), [1])
    const reopen = state.store.fetchAgents()
    assert.equal(state.requests.length, 2, 'reopening still retrieves current data')
    state.requests[1].resolve({ data: [{ id: 2 }] })
    await reopen
    assert.deepEqual(state.store.agents.map(agent => agent.id), [2])
  } finally { state.close() }
})

test('a late failure from the previous session cannot empty the new session agents', async () => {
  const state = setup()
  try {
    const old = state.store.fetchAgents()
    state.switchSession()
    const current = state.store.fetchAgents()
    assert.equal(state.requests.length, 2)
    state.requests[1].resolve({ data: [{ id: 2 }] })
    await current
    state.requests[0].reject(new Error('Superseded session'))
    await old
    assert.deepEqual(state.store.agents.map(agent => agent.id), [2])
    assert.equal(state.store.error, null)
  } finally { state.close() }
})
