import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

test('revision pages are bounded and a late page cannot replace another item', async () => {
  const pending = deferred()
  const calls = []
  const service = {
    getItem: async id => ({ id }), listLinks: async () => [],
    listRevisions: async (id, agentId, limit, offset = 0) => {
      calls.push({ id, limit, offset })
      if (offset) return pending.promise
      return Array.from({ length: limit }, (_, index) => ({ revision: index + 1 }))
    },
  }
  const { useMemoryStore } = loadTypescript(new URL('./stores/memoryStore.ts', import.meta.url), {
    pinia, vue, '../services/memoryService': { memoryService: service },
    '@/app/document': { documentService: {} },
    '@/core/websocket': { websocket: { createWebsocket() {}, onEvent() {}, offEvent() {}, onConnect() {}, offConnect() {} } },
  })
  const store = useMemoryStore(pinia.createPinia())
  store.selectedAgentId = 1
  await store.openItem('first')
  const more = store.loadMoreRevisions()
  await store.openItem('second')
  pending.resolve([{ revision: 999 }])
  await more
  assert.equal(store.currentItem.id, 'second')
  assert.equal(store.revisions.length, 50)
  assert.deepEqual(calls, [
    { id: 'first', limit: 50, offset: 0 }, { id: 'first', limit: 50, offset: 50 },
    { id: 'second', limit: 50, offset: 0 },
  ])
})

for (const trigger of ['memory.invalidate', 'connect']) test(`${trigger} rechecks a pending detail without applying stale failures or another agent's response`, async () => {
  const first = deferred(), later = deferred(), callbacks = {}
  let reads = 0, hold = false
  const service = {
    getItem: async id => {
      reads++
      if (reads === 1) return first.promise
      if (hold) { hold = false; return later.promise }
      return { id }
    },
    listLinks: async () => [], listRevisions: async () => [],
    temporalDefaults: async () => ({ timezone: 'UTC' }),
    browse: async () => ({ hits: [], total: 0, has_more: false }),
    listFindings: async () => [],
  }
  const { useMemoryStore } = loadTypescript(new URL('./stores/memoryStore.ts', import.meta.url), {
    pinia, vue, '../services/memoryService': { memoryService: service },
    '@/app/document': { documentService: {} },
    '@/core/websocket': { websocket: {
      createWebsocket() {}, offEvent() {}, offConnect() {},
      onEvent(domain, event, callback) { callbacks[`${domain}.${event}`] = callback },
      onConnect(callback) { callbacks.connect = callback },
    } },
  })
  const store = useMemoryStore(pinia.createPinia())
  store.selectedAgentId = 7
  const opening = store.openItem('first').catch(error => error)
  callbacks[trigger]()
  assert.equal(reads, 2)
  assert.equal(store.currentItem, null)
  await new Promise(setImmediate)
  assert.equal(store.currentItem.id, 'first')
  await store.openItem('second')
  first.reject(new Error('Synthetic obsolete request failure'))
  assert.match((await opening).message, /obsolete request/)
  assert.equal(store.currentItem.id, 'second')
  assert.equal(store.error, null)
  assert.equal(store.detailError, null)

  hold = true
  callbacks[trigger]()
  assert.equal(store.currentItem, null)
  store.selectedAgentId = 8
  await store.openItem('another-agent')
  later.resolve({ id: 'second' })
  await new Promise(setImmediate)
  assert.equal(store.currentItem.id, 'another-agent')
  assert.equal(store.selectedAgentId, 8)
})
