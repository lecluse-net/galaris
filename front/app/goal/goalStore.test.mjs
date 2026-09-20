import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'

function setup() {
  const requests = new Map()
  const { useGoalStore } = loadTypescript(new URL('./stores/goalStore.ts', import.meta.url), {
    vue, pinia,
    '@/core/api': { sessionGeneration: () => 'test' },
    '@/core/websocket': { websocket: {} },
    '@/core/user/stores/authStore': {},
    '../services/goalService': { goalService: {
      get(id) { const request = deferred(); requests.set(id, request); return request.promise },
      async listCycles(id) { return { items: [{ id: `cycle-${id}` }], page: 1, page_size: 50, total: 1 } },
    } },
  })
  return { store: useGoalStore(pinia.createPinia()), requests }
}

test('late detail response cannot replace the selected Goal or its cycles', async () => {
  const { store, requests } = setup()
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
