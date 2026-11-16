import * as vue from 'vue'
import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'
import { sessionStoreScope } from '../../test-support/session-store.mjs'

test('executor status and availability reject old reads after retry and session replacement', async () => {
  const window = new EventTarget(), statuses = [], availability = []
  let session = 'first'
  const scope = sessionStoreScope(window, () => session)
  const { useConsoleStore } = loadTypescript(new URL('./stores/consoleStore.ts', import.meta.url), {
    vue, pinia, '@/core/api': { sessionGeneration: () => session }, '@/core/util/facade': scope,
    '../services/consoleService': { consoleService: {
      status() { const request = deferred(); statuses.push(request); return request.promise },
      availability() { const request = deferred(); availability.push(request); return request.promise },
    } },
  })
  const store = useConsoleStore(pinia.createPinia())
  try {
    const old = store.refresh(), latest = store.refresh()
    statuses[1].resolve({ data: { ok: true, result: { version: 'current' } } }); await latest
    statuses[0].reject(Error('obsolete failure')); await old
    assert.equal(store.status.version, 'current'); assert.equal(store.error, '')
    const previousAvailability = store.loadAvailability(), previousStatus = store.refresh()
    session = 'second'; window.dispatchEvent(new Event('auth'))
    const currentAvailability = store.loadAvailability(), currentStatus = store.refresh()
    availability[1].resolve({ data: { in_use: true } }); await currentAvailability
    statuses[3].resolve({ data: { ok: true, result: { version: 'other session' } } }); await currentStatus
    availability[0].resolve({ data: { in_use: false } }); await previousAvailability
    statuses[2].reject(Error('previous session')); await previousStatus
    assert.equal(store.availability, true); assert.equal(store.status.version, 'other session')
    assert.equal(store.error, ''); assert.equal(store.loading, false)
    const failed = store.refresh(); statuses[4].reject(Error('current outage')); await failed
    assert.equal(store.error, 'current outage')
    assert.equal(scope.storeRequests(store).refresh.error.message, 'current outage')
  } finally { store.$dispose() }
})
