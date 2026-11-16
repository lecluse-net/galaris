import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

function memoryStore(service) {
  const { useMemoryStore } = loadTypescript(new URL('./stores/memoryStore.ts', import.meta.url), {
    pinia, vue, '../services/memoryService': { memoryService: service },
    '@/app/document': { documentService: {} },
    '@/core/websocket': { websocket: { createWebsocket() {}, onEvent() {}, offEvent() {}, onConnect() {}, offConnect() {} } },
  })
  return useMemoryStore(pinia.createPinia())
}

const page = id => ({ hits: [{ item: { id } }], total: 1, has_more: false })

test('memory loading starts independent requests together and publishes one consistent page', async () => {
  const defaults = deferred(), browse = deferred(), findings = deferred(), calls = []
  const store = memoryStore({
    temporalDefaults: () => { calls.push('defaults'); return defaults.promise },
    browse: params => { calls.push(['browse', params]); return browse.promise },
    listFindings: agentId => { calls.push(['findings', agentId]); return findings.promise },
  })
  store.selectedAgentId = 7
  store.query = 'Synthetic query'
  const loading = store.search()
  try {
    assert.equal(calls.length, 3, 'Items and findings must start without waiting for temporal defaults')
    assert.deepEqual(calls.find(call => Array.isArray(call) && call[0] === 'findings'), ['findings', 7])
    const params = calls.find(call => Array.isArray(call) && call[0] === 'browse')[1]
    assert.equal(params.agentId, 7)
    assert.equal(params.query, 'Synthetic query')
    assert.equal(store.loading, true)
    assert.deepEqual(store.hits, [])
  } finally {
    defaults.resolve({ timezone: 'UTC' })
    browse.resolve(page('current'))
    findings.resolve([{ id: 'current-finding' }])
    await loading
    store.$dispose()
  }
  assert.equal(store.hits[0].item.id, 'current')
  assert.equal(store.findings[0].id, 'current-finding')
  assert.equal(store.loading, false)
})

test('parallel memory loads discard another agent and superseded search responses', async () => {
  const oldBrowse = deferred(), oldFindings = deferred(), currentBrowse = deferred()
  void oldFindings.promise.catch(() => {})
  const store = memoryStore({
    temporalDefaults: async () => ({ timezone: 'UTC' }),
    browse: ({ agentId }) => agentId === 7 ? oldBrowse.promise : currentBrowse.promise,
    listFindings: agentId => agentId === 7 ? oldFindings.promise : Promise.resolve([{ id: 'current-finding' }]),
  })
  store.selectedAgentId = 7
  const previous = store.search()
  store.selectedAgentId = 8
  store.query = 'Current query'
  const current = store.search()
  oldBrowse.resolve(page('private-old-agent'))
  oldFindings.reject(new Error('Synthetic stale failure'))
  await previous
  assert.deepEqual(store.hits, [])
  assert.equal(store.loading, true)
  assert.equal(store.error, null)
  currentBrowse.resolve(page('current-agent'))
  await current
  assert.equal(store.hits[0].item.id, 'current-agent')
  assert.equal(store.findings[0].id, 'current-finding')
  assert.equal(store.loading, false)
  store.$dispose()
})

test('parallel memory loading retains error recovery and clamps an obsolete page', async () => {
  let fail = true
  const offsets = []
  const store = memoryStore({
    temporalDefaults: async () => ({ timezone: 'UTC' }),
    browse: async ({ offset }) => { offsets.push(offset); return offset ? { hits: [], total: 1, has_more: false } : page('remaining') },
    listFindings: async () => { if (fail) throw new Error('Synthetic findings failure'); return [] },
  })
  store.selectedAgentId = 7
  await assert.rejects(store.search({ page: 4 }), /findings failure/)
  assert.equal(store.page, 1)
  assert.equal(store.loading, false)
  assert.deepEqual(store.hits, [])
  fail = false
  await store.search({ page: 4 })
  assert.equal(store.page, 1)
  assert.equal(store.total, 1)
  assert.equal(store.hits[0].item.id, 'remaining')
  assert.equal(offsets.at(-1), 0)
  assert.equal(store.error, null)
  store.$dispose()
})
