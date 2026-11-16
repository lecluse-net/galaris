import * as vue from 'vue'
import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'
import { sessionStoreScope } from '../../test-support/session-store.mjs'

test('a cleared overview cannot be restored by an old read and the next read recovers', async () => {
  const reads = []
  const { useOnboardingStore } = loadTypescript(new URL('./stores/onboardingStore.ts', import.meta.url), {
    vue, pinia, '@/core/api': { sessionGeneration: () => 'synthetic-session' }, '@/core/util/facade': sessionStoreScope(),
    '../services/onboardingService': { __esModule: true, default: { getOverview: () => { const read = deferred(); reads.push(read); return read.promise } } },
  })
  const store = useOnboardingStore(pinia.createPinia())
  const old = store.fetchOverview(); store.clearState()
  reads[0].resolve({ language_configured: true, llm_provider: { has_data: true } }); await old
  assert.equal(store.isLoaded, false)
  const current = store.fetchOverview(); reads[1].resolve({ language_configured: false, llm_provider: { has_data: false } }); await current
  assert.equal(store.languageConfigured, false); assert.equal(store.loading, false)
  store.$dispose()
})
