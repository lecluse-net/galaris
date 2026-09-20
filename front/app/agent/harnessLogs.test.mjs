import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'
import { startVisiblePolling } from '../../core/util/visiblePolling.ts'

test('log selection ignores reversed responses and closing prevents polling revival', async () => {
  const { useHarnessLogs } = loadTypescript(new URL('./composables/useHarnessLogs.ts', import.meta.url), {
    vue, '@/core/api': { sessionGeneration: () => 'one' },
    '@/core/util': { startVisiblePolling: (refresh, interval) => startVisiblePolling(refresh, interval, Object.assign(new EventTarget(), { hidden: false })) },
  })
  const requests = new Map()
  const scope = vue.effectScope()
  const logs = scope.run(() => useHarnessLogs(id => {
    const request = deferred(); requests.set(id, request); return request.promise
  }, () => 'fallback'))
  try {
    const a = logs.openHarnessLogs({ id: 1, code: 'A' })
    const b = logs.openHarnessLogs({ id: 2, code: 'B' })
    requests.get(2).resolve(['B']); await b
    requests.get(1).reject(new Error('A unavailable')); await a
    assert.deepEqual([...logs.harnessLogs.value], ['B'])
    assert.equal(logs.harnessLogsLoading.value, false)
    const c = logs.openHarnessLogs({ id: 3, code: 'C' })
    logs.closeHarnessLogs()
    requests.get(3).resolve(['C']); await c
    assert.deepEqual([...logs.harnessLogs.value], [])
    assert.equal(logs.showHarnessLogsDialog.value, false)
  } finally { scope.stop() }
})
