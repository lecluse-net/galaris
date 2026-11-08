import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'

function setup(overrides = {}) {
  const requests = new Map()
  const events = new Map()
  const calls = { list: 0, tree: 0, detail: 0, cycles: 0 }
  const service = {
    get(id) { calls.detail++; const request = deferred(); requests.set(id, request); return request.promise },
    async list() { calls.list++; return { items: [], total: 0, summary: {}, tracking_llm_configured: true } },
    async tree() { calls.tree++; return { items: [], total: 0 } },
    async listCycles(id) { calls.cycles++; return { items: [{ id: `cycle-${id}` }], page: 1, page_size: 50, total: 1 } },
    ...overrides,
  }
  const { useGoalStore } = loadTypescript(new URL('./stores/goalStore.ts', import.meta.url), {
    vue, pinia,
    '@/core/api': { sessionGeneration: () => 'test' },
    '@/core/websocket': { websocket: {
      createWebsocket() {},
      onEvent(resource, action, listener) { events.set(`${resource}:${action}`, listener) },
      offEvent(resource, action) { events.delete(`${resource}:${action}`) },
    } },
    '@/core/user/stores/authStore': { useAuthStore: () => ({ user: { id: 1 } }) },
    '@/core/authorize': { privileges: { GOAL_CONFIG_ACCESS: 'GOAL_CONFIG_ACCESS', GOAL_CONFIG_EDIT: 'GOAL_CONFIG_EDIT' },
      usePrivilegeStore: () => ({ hasAnyPrivilege: () => true }) },
    '../services/goalService': { goalService: service },
  })
  return { store: useGoalStore(pinia.createPinia()), requests, events, calls }
}

test('late detail response cannot replace the selected Goal or its cycles', async () => {
  const { store, requests } = setup()
  await store.setCyclesActive(true)
  const a = store.fetchGoal('A')
  const b = store.fetchGoal('B')
  requests.get('B').resolve({ id: 'B', revision: 1 })
  await b
  requests.get('A').resolve({ id: 'A', revision: 1 })
  assert.equal(await a, null)
  assert.equal(store.currentGoal.id, 'B')
  assert.equal(store.cycles[0].id, 'cycle-B')
  store.$dispose()
})

test('opening a Goal loads its history only when the cycles tab is requested', async () => {
  const { store, requests, calls } = setup()
  const pending = store.fetchGoal('A')
  requests.get('A').resolve({ id: 'A', revision: 1 })
  await pending
  assert.equal(calls.cycles, 0)
  await store.setCyclesActive(true)
  assert.equal(calls.cycles, 1)
  await store.setCyclesActive(false)
  assert.equal(store.currentGoal.id, 'A')
  store.$dispose()
})

const settle = async () => { for (let i = 0; i < 15; i++) await Promise.resolve() }

test('a burst of Task events refreshes the list once without reloading the tree or an unrelated selection', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { store, events, calls } = setup()
  store.currentGoal = { id: 'A', revision: 1 }
  store.subscribe()
  for (let i = 0; i < 20; i++) events.get('task:update')({ data: { goal_id: 'B' } })
  t.mock.timers.tick(300)
  await settle()
  assert.deepEqual(calls, { list: 1, tree: 0, detail: 0, cycles: 0 })
  store.$dispose()
})

test('live refreshes never overlap and retain one subsequent update', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const pending = []
  const { store, events } = setup({ list() { const request = deferred(); pending.push(request); return request.promise } })
  store.subscribe()
  events.get('task:update')({ data: { goal_id: 'A' } })
  t.mock.timers.tick(300)
  await settle()
  events.get('task:update')({ data: { goal_id: 'A' } })
  t.mock.timers.tick(300)
  await settle()
  assert.equal(pending.length, 1)
  pending[0].resolve({ items: [], total: 0, summary: {}, tracking_llm_configured: true })
  await settle()
  t.mock.timers.tick(300)
  await settle()
  assert.equal(pending.length, 2)
  pending[1].resolve({ items: [], total: 0, summary: {}, tracking_llm_configured: true })
  await settle()
  store.$dispose()
})

test('closing the selection discards late success and errors', async () => {
  for (const failed of [false, true]) {
    const { store, requests } = setup()
    const pending = store.fetchGoal('A')
    store.clearSelection()
    if (failed) requests.get('A').reject(new Error('old failure'))
    else requests.get('A').resolve({ id: 'A', revision: 1 })
    assert.equal(await pending, null)
    assert.equal(store.currentGoal, null)
    assert.equal(store.detailLoading, false)
    store.$dispose()
  }
})

test('hiding cycles discards a late failure without changing the selected Goal', async () => {
  const history = deferred()
  const { store } = setup({ listCycles: () => history.promise })
  store.currentGoal = { id: 'A', revision: 1 }
  const pending = store.setCyclesActive(true)
  await store.setCyclesActive(false)
  history.reject(new Error('Synthetic obsolete history failure'))
  await pending
  assert.equal(store.cyclesError, null)
  assert.equal(store.cyclesLoading, false)
  assert.equal(store.currentGoal.id, 'A')
  store.$dispose()
})

test('pagination jumps directly to the last remaining page after removals', async () => {
  const pages = []
  const { store } = setup({ async list({ skip }) {
    pages.push(skip)
    return { items: skip > 50 ? [] : [{ id: 'A', revision: 1 }], total: 51, summary: {}, tracking_llm_configured: true }
  } })
  await store.fetchGoals(30)
  assert.deepEqual(pages, [1500, 50])
  assert.equal(store.page, 1)
  assert.equal(store.loading, false)
  store.$dispose()
})

test('a background error is retained for retry and does not stop later updates', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let attempts = 0
  const failure = new Error('Synthetic temporary list failure')
  const { store, events } = setup({ async list() {
    if (++attempts === 1) throw failure
    return { items: [{ id: 'A', revision: 2 }], total: 1, summary: {}, tracking_llm_configured: true }
  } })
  store.goals = [{ id: 'A', revision: 1 }]
  store.subscribe()
  events.get('task:update')({ data: { goal_id: 'A' } })
  t.mock.timers.tick(300)
  await settle()
  assert.equal(store.error, failure)
  assert.equal(store.goals[0].revision, 1)
  events.get('task:update')({ data: { goal_id: 'A' } })
  t.mock.timers.tick(300)
  await settle()
  assert.equal(store.error, null)
  assert.equal(store.goals[0].revision, 2)
  store.$dispose()
})

test('unsubscribing discards queued live refreshes', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { store, events, calls } = setup()
  store.subscribe()
  events.get('task:update')({ data: { goal_id: 'A' } })
  store.unsubscribe()
  t.mock.timers.tick(300)
  await settle()
  assert.deepEqual(calls, { list: 0, tree: 0, detail: 0, cycles: 0 })
  store.$dispose()
})

test('updating a parent refreshes its selected child without loading history', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { store, events, requests, calls } = setup()
  store.currentGoal = { id: 'child', revision: 1, parent_goal_id: 'parent' }
  store.treeGoals = [{ id: 'parent', title: 'Synthetic parent', parent_goal_id: null, agent_id: 1 }]
  store.subscribe()
  events.get('goal:update')({ data: { id: 'parent', title: 'Synthetic renamed parent', revision: 2, parent_goal_id: null, agent_id: 1 } })
  t.mock.timers.tick(300)
  await settle()
  requests.get('child').resolve({ id: 'child', revision: 1, parent_goal_id: 'parent', parent_title: 'Synthetic renamed parent' })
  await settle()
  assert.equal(store.currentGoal.parent_title, 'Synthetic renamed parent')
  assert.deepEqual(calls, { list: 1, tree: 1, detail: 1, cycles: 0 })
  store.$dispose()
})

test('a late mutation cannot replace a new selection after leaving the view', async () => {
  const update = deferred()
  const { store } = setup({ update: () => update.promise })
  store.goals = [{ id: 'A', revision: 1 }]
  const pending = store.updateGoal('A', { expected_revision: 1, title: 'Synthetic change' })
  store.unsubscribe()
  store.currentGoal = { id: 'B', revision: 1 }
  update.resolve({ id: 'A', revision: 2 })
  await pending
  assert.equal(store.currentGoal.id, 'B')
  assert.equal(store.goals[0].revision, 1)
  store.$dispose()
})

test('late runtime settings cannot overwrite a new view context', async () => {
  const update = deferred()
  const { store } = setup({ updateSettings: () => update.promise })
  const pending = store.updateSettings({ globally_paused: true })
  store.unsubscribe()
  store.settings = { globally_paused: false }
  update.resolve({ globally_paused: true })
  await pending
  assert.equal(store.settings.globally_paused, false)
  assert.equal(store.settingsSaving, false)
  store.$dispose()
})

test('an empty last page with a concurrent count change still makes progress', async () => {
  const pages = []
  const { store } = setup({ async list({ skip }) {
    pages.push(skip)
    if (pages.length > 2) throw new Error('Pagination did not make progress')
    return { items: skip ? [] : [{ id: 'A', revision: 1 }], total: 100, summary: {}, tracking_llm_configured: true }
  } })
  await store.fetchGoals(1)
  assert.deepEqual(pages, [50, 0])
  store.$dispose()
})
