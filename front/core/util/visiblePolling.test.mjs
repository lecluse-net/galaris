import assert from 'node:assert/strict'
import test from 'node:test'
import { startVisiblePolling } from './visiblePolling.ts'

class Visibility extends EventTarget {
  hidden = false
  change(hidden) { this.hidden = hidden; this.dispatchEvent(new Event('visibilitychange')) }
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }

test('visible refresh cadence is preserved; a hidden minute makes no requests; return refreshes immediately', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const visibility = new Visibility()
  let calls = 0
  const stop = startVisiblePolling(() => { calls++ }, 2000, visibility)
  for (let i = 0; i < 30; i++) { t.mock.timers.tick(2000); await flush() }
  assert.equal(calls, 30)
  visibility.change(true)
  t.mock.timers.tick(60_000)
  await flush()
  assert.equal(calls, 30)
  visibility.change(false)
  await flush()
  assert.equal(calls, 31)
  stop()
  visibility.change(true); visibility.change(false)
  t.mock.timers.tick(60_000)
  assert.equal(calls, 31)
})

test('slow requests never overlap, including hide and return while a request is running', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const visibility = new Visibility()
  let calls = 0, finish
  const stop = startVisiblePolling(() => {
    calls++
    return new Promise(resolve => { finish = resolve })
  }, 2000, visibility)
  t.mock.timers.tick(2000)
  t.mock.timers.tick(60_000)
  visibility.change(true); visibility.change(false)
  assert.equal(calls, 1)
  finish(); await flush()
  assert.equal(calls, 2)
  stop()
  finish(); await flush()
  t.mock.timers.tick(60_000)
  assert.equal(calls, 2)
})

test('initially hidden views wait until visible and a failed refresh does not stop later refreshes', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const visibility = new Visibility()
  visibility.hidden = true
  let calls = 0
  const errors = []
  const stop = startVisiblePolling(async () => { if (++calls === 1) throw new Error('offline') }, 2000, visibility, error => errors.push(error))
  t.mock.timers.tick(60_000)
  assert.equal(calls, 0)
  visibility.change(false); await flush()
  assert.equal(errors.length, 1)
  t.mock.timers.tick(2000); await flush()
  assert.equal(calls, 2)
  stop()
})

test('completion after hiding does not recreate a background timer', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const visibility = new Visibility()
  let calls = 0, finish
  const stop = startVisiblePolling(() => { calls++; return new Promise(resolve => { finish = resolve }) }, 2000, visibility)
  t.mock.timers.tick(2000)
  visibility.change(true)
  finish(); await flush()
  t.mock.timers.tick(60_000)
  assert.equal(calls, 1)
  stop()
})
