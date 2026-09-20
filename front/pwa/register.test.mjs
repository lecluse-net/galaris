import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate } from 'node:timers/promises'
import { loadTypescript } from '../test-support/load-typescript.mjs'

function register(update, { online = true, visible = true, installing = null } = {}) {
  const handlers = {}
  const navigator = { onLine: online }
  const document = { visibilityState: visible ? 'visible' : 'hidden', addEventListener: (name, callback) => { handlers[name] = callback } }
  loadTypescript(new URL('./register.ts', import.meta.url), {
    'virtual:pwa-register': { registerSW: options => options.onRegisteredSW('/sw.js', { update, installing }) },
    '../core/settings': { settings: { is_dev: false } },
  }, {
    navigator, document,
    window: { setInterval: callback => { handlers.timer = callback }, addEventListener: (name, callback) => { handlers[name] = callback } },
  })
  return { handlers, navigator, document }
}

test('an update requested during a failed check is retried when that check finishes', async () => {
  let rejectFirst, calls = 0
  const first = new Promise((_, reject) => { rejectFirst = reject })
  const runtime = register(() => ++calls === 1 ? first : Promise.resolve())
  runtime.handlers.timer()
  runtime.handlers.online()
  assert.equal(calls, 1)
  rejectFirst(new Error('Invalid deployment'))
  await setImmediate()
  assert.equal(calls, 2)
  await setImmediate()
  assert.equal(calls, 2) // No automatic loop after an idle or failed deployment.
})

test('hidden clients defer checks until they can observe an update', async () => {
  let calls = 0
  const runtime = register(async () => { calls++ }, { visible: false })
  runtime.handlers.timer()
  assert.equal(calls, 0)
  runtime.document.visibilityState = 'hidden'
  runtime.navigator.onLine = true
  runtime.handlers.online()
  assert.equal(calls, 0)
  runtime.document.visibilityState = 'visible'
  runtime.handlers.visibilitychange()
  await setImmediate()
  assert.equal(calls, 1)
})

test('an offline hint cannot block reachable updates and failed checks preserve later retries', async () => {
  let calls = 0
  const runtime = register(async () => {
    if (++calls === 1) throw new Error('Network unavailable')
  }, { online: false })
  await setImmediate()
  assert.equal(calls, 1)
  runtime.handlers.timer()
  await setImmediate()
  assert.equal(calls, 2)
  await setImmediate()
  assert.equal(calls, 2)
})
