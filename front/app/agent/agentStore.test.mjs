import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import * as axios from 'axios'
import { setImmediate } from 'node:timers/promises'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'
import { sessionReadCache } from '../../test-support/session-read-cache.mjs'

function setup() {
  let generation = 'one'
  const requests = []
  const window = new EventTarget()
  const api = { sessionGeneration: () => generation, AUTH_TOKEN_CHANGED_EVENT: 'auth', __esModule: true,
    default: { get() { const pending = deferred(); requests.push(pending); return pending.promise } } }
  const services = loadTypescript(new URL('./services/agentService.ts', import.meta.url), {
    '@/core/api': api, '@/core/util/facade': sessionReadCache(window),
  })
  const titleLabels = loadTypescript(new URL('./titleLabels.ts', import.meta.url), {})
  const { useAgentStore } = loadTypescript(new URL('./stores/agentStore.ts', import.meta.url), {
    pinia, axios,
    '@/core/api': api,
    '../titleLabels': titleLabels,
    '../services/agentService': services,
  })
  const store = useAgentStore(pinia.createPinia())
  return { store, requests, switchSession: () => { generation = 'two'; window.dispatchEvent(new Event('auth')) }, close: () => store.$dispose() }
}

test('simultaneous page and widget loads share one agents request and all await its data', async () => {
  const state = setup()
  try {
    const loads = Array.from({ length: 30 }, () => state.store.fetchAgents())
    await setImmediate()
    assert.equal(state.requests.length, 1)
    state.requests[0].resolve({ data: [{ id: 1 }] })
    await Promise.all(loads)
    assert.deepEqual(state.store.agents.map(agent => agent.id), [1])
    await state.store.fetchAgents()
    assert.equal(state.requests.length, 1, 'reopening reuses the fresh catalogue')
    const reopen = state.store.fetchAgents(true)
    await setImmediate()
    assert.equal(state.requests.length, 2, 'explicit refresh retrieves current data')
    state.requests[1].resolve({ data: [{ id: 2 }] })
    await reopen
    assert.deepEqual(state.store.agents.map(agent => agent.id), [2])
  } finally { state.close() }
})

test('a late failure from the previous session cannot empty the new session agents', async () => {
  const state = setup()
  try {
    const old = state.store.fetchAgents()
    await setImmediate()
    state.switchSession()
    const current = state.store.fetchAgents()
    await setImmediate()
    assert.equal(state.requests.length, 2)
    state.requests[1].resolve({ data: [{ id: 2 }] })
    await current
    state.requests[0].reject(new Error('Superseded session'))
    await old
    assert.deepEqual(state.store.agents.map(agent => agent.id), [2])
    assert.equal(state.store.error, null)
  } finally { state.close() }
})

test('forced catalogue refresh wins over a late response and a denied refresh removes old options', async () => {
  const state = setup()
  try {
    const old = state.store.fetchAgents()
    await setImmediate()
    const refresh = state.store.fetchAgents(true)
    await setImmediate()
    state.requests[1].resolve({ data: [{ id: 2 }] })
    await refresh
    state.requests[0].resolve({ data: [{ id: 1 }] })
    await old
    assert.deepEqual(state.store.agents.map(agent => agent.id), [2])
    const denied = state.store.fetchAgents(true)
    await setImmediate()
    state.requests[2].reject(new Error('forbidden'))
    await denied
    assert.deepEqual(state.store.agents, [])
    const retry = state.store.fetchAgents()
    await setImmediate()
    state.requests[3].resolve({ data: [] })
    await retry
    await state.store.fetchAgents()
    assert.equal(state.requests.length, 4, 'empty lists are cacheable but errors are not')
  } finally { state.close() }
})
