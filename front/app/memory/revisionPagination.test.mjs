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
