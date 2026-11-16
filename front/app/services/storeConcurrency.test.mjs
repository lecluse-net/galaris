import * as vue from 'vue'
import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'
import { sessionStoreScope } from '../../test-support/session-store.mjs'

test('a late catalogue cannot undo a service mutation and the next read recovers', async () => {
  const reads = []
  const { useServiceStore } = loadTypescript(new URL('./stores/serviceStore.ts', import.meta.url), {
    vue, pinia, '@/core/api': { sessionGeneration: () => 'synthetic-session' }, '@/core/util/facade': sessionStoreScope(),
    '../services/serviceApi': { __esModule: true, default: {
      getServices: () => { const read = deferred(); reads.push(read); return read.promise },
      deleteService: async () => undefined,
      updateService: async id => ({ data: { id, label: 'Updated synthetic service' } }),
    } },
  })
  const store = useServiceStore(pinia.createPinia())
  store.services = [{ id: 1, label: 'Synthetic service' }]
  for (const mutate of [() => store.updateService(1, {}), () => store.deleteService(1)]) {
    const pending = store.fetchServices()
    await mutate()
    const expected = structuredClone(pinia.storeToRefs(store).services.value.map(value => ({ ...value })))
    reads.at(-1).resolve({ data: [{ id: 1, label: 'Obsolete service' }] }); await pending
    assert.deepEqual(store.services.map(value => ({ ...value })), expected)
  }
  const retry = store.fetchServices(); reads.at(-1).resolve({ data: [] }); await retry
  assert.deepEqual(store.services, []); assert.equal(store.loading, false)
  store.$dispose()
})
