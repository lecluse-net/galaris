import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import * as axios from 'axios'
import { loadTypescript } from '../../test-support/load-typescript.mjs'
import { sessionReadCache } from '../../test-support/session-read-cache.mjs'

test('preferences reuse parameters across sections, refresh after edits, expiry and session changes', async t => {
  t.mock.timers.enable({ apis: ['Date'], now: 0 })
  const window = new EventTarget()
  let generation = 'one', value = 'initial', reads = 0, denied = false
  const parameter = () => ({ name: 'synthetic_setting', value, secret: false, configured: true, prompt: null })
  const api = { __esModule: true, AUTH_TOKEN_CHANGED_EVENT: 'auth', sessionGeneration: () => generation, default: {
    get: async () => {
      reads++
      if (denied === 'offline') throw Error('offline')
      if (denied) throw Object.assign(Error('forbidden'), { isAxiosError: true, response: { status: 403 } })
      return { data: { params: [parameter()] } }
    },
    put: async (_url, update) => { value = update.value; return { data: parameter() } },
  } }
  const services = loadTypescript(new URL('./services/paramsService.ts', import.meta.url), {
    '@/core/api': api, '@/core/util/facade': sessionReadCache(window),
  })
  const { useParamsStore } = loadTypescript(new URL('./stores/paramsStore.ts', import.meta.url), {
    pinia, axios, '@/core/api': api, '../services/paramsService': services,
  })
  const store = useParamsStore(pinia.createPinia())
  try {
    await Promise.all(Array.from({ length: 20 }, () => store.fetchParams()))
    await store.fetchParams()
    assert.equal(reads, 1)
    store.params[0].value = 'unsaved local edit'
    await store.fetchParams()
    assert.equal(store.getParamValue('synthetic_setting'), 'initial')
    await store.updateParam('synthetic_setting', 'saved')
    await store.fetchParams()
    assert.equal(reads, 2)
    assert.equal(store.getParamValue('synthetic_setting'), 'saved')
    value = 'another client'
    await store.fetchParams(true)
    assert.equal(store.getParamValue('synthetic_setting'), 'another client')
    t.mock.timers.tick(300_001)
    await store.fetchParams()
    assert.equal(reads, 4)
    generation = 'two'
    window.dispatchEvent(new Event('auth'))
    denied = true
    await store.fetchParams()
    assert.deepEqual(store.params, [])
    denied = false
    await store.fetchParams()
    assert.equal(reads, 6)
    store.params[0].value = 'draft to preserve'
    denied = 'offline'
    await store.fetchParams(true)
    assert.equal(store.getParamValue('synthetic_setting'), 'draft to preserve')
  } finally { store.$dispose() }
})
