import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

test('visible progress uses the socket snapshot while changes to page membership coalesce', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const handlers = new Map()
  const task = { id: 'synthetic', status: 'RUNNING', revision: 1 }
  const page = { items: [task], total: 1, summary: { running: 1 } }
  const delayed = deferred()
  let calls = 0
  const { useTaskStore } = loadTypescript(new URL('./stores/taskStore.ts', import.meta.url), {
    pinia, vue,
    '../services/taskService': { taskService: { getRecent: () => ++calls === 2 ? delayed.promise : Promise.resolve(page) } },
    '@/core/websocket': { websocket: {
      createWebsocket() {}, onConnect() {}, offConnect() {}, offEvent() {},
      onEvent(_subject, action, handler) { handlers.set(action, handler) },
    } },
    '@/core/user/facade': { useAuthStore: () => ({ user: { id: 1 } }) },
    '../taskSnapshot': loadTypescript(new URL('./taskSnapshot.ts', import.meta.url), {}),
    '../aiResult': {},
  })
  const store = useTaskStore(pinia.createPinia())
  try {
    await store.fetchRecentTasks()
    store.subscribeToTasks()
    for (let revision = 2; revision <= 30; revision++) {
      handlers.get('update')({ data: { ...task, revision } })
      t.mock.timers.tick(100)
    }
    assert.equal(store.recentTasks[0].revision, 30)
    assert.equal(calls, 1)
    for (let index = 0; index < 10; index++) {
      handlers.get('create')()
      t.mock.timers.tick(100)
    }
    assert.equal(calls, 2)
    handlers.get('update')({ data: { ...task, revision: 31, status: 'SUCCESS' } })
    delayed.resolve(page)
    await delayed.promise
    assert.equal(store.recentTasks[0].status, 'SUCCESS')
    t.mock.timers.tick(301)
    assert.equal(calls, 3)
  } finally {
    store.unsubscribeFromTasks()
    store.$dispose()
  }
})

test('a stale empty task response cannot decrement the current page or refetch it', async () => {
  const old = deferred(), current = deferred()
  let calls = 0
  const { useTaskStore } = loadTypescript(new URL('./stores/taskStore.ts', import.meta.url), {
    pinia, vue,
    '../services/taskService': { taskService: { getRecent: () => ++calls === 1 ? old.promise : current.promise } },
    '@/core/websocket': { websocket: {} },
    '@/core/user/facade': { useAuthStore: () => ({}) },
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

test('leaving tasks cancels a queued refresh and ignores an outstanding list', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const read = deferred(); let calls = 0
  const { useTaskStore } = loadTypescript(new URL('./stores/taskStore.ts', import.meta.url), {
    pinia, vue,
    '../services/taskService': { taskService: { run: async () => ({ id: 'synthetic-task' }), getRecent: () => { calls++; return read.promise } } },
    '@/core/websocket': { websocket: {} }, '@/core/user/facade': { useAuthStore: () => ({}) },
    '../taskSnapshot': { mergeTaskSnapshot: (_, value) => value }, '../aiResult': {},
  })
  const store = useTaskStore(pinia.createPinia())
  await store.runTask('synthetic-task')
  const pending = store.fetchRecentTasks()
  store.unsubscribeFromTasks(); t.mock.timers.tick(1000)
  read.resolve({ items: [{ id: 'obsolete' }], total: 1, summary: {} }); await pending
  assert.equal(calls, 1); assert.deepEqual(store.recentTasks, []); assert.equal(store.recentLoading, false)
  store.$dispose()
})
