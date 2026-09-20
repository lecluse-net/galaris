import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

test('a stale empty task response cannot decrement the current page or refetch it', async () => {
  const old = deferred(), current = deferred()
  let calls = 0
  const { useTaskStore } = loadTypescript(new URL('./stores/taskStore.ts', import.meta.url), {
    pinia, vue,
    '../services/taskService': { taskService: { getRecent: () => ++calls === 1 ? old.promise : current.promise } },
    '@/core/websocket': { websocket: {} },
    '@/core/user/stores/authStore': { useAuthStore: () => ({}) },
    '../taskSnapshot': { mergeTaskSnapshot: (old, next) => next },
    '../aiResult': {},
  })
  const store = useTaskStore(pinia.createPinia())
  const first = store.fetchRecentTasks(1)
  const second = store.fetchRecentTasks(3)
  current.resolve({ items: [{ id: 'current' }], total: 200, summary: {} })
  await second
  old.resolve({ items: [], total: 0, summary: {} })
  await first
  assert.equal(store.recentPage, 3)
  assert.equal(store.recentTasks[0].id, 'current')
  assert.equal(calls, 2)
})
