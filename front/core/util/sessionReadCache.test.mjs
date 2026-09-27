import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate } from 'node:timers/promises'
import { deferred } from '../../test-support/load-typescript.mjs'
import { sessionReadCache } from '../../test-support/session-read-cache.mjs'

test('fresh reads coalesce, expire, evict within the byte budget and never retain failures', async t => {
  t.mock.timers.enable({ apis: ['Date'], now: 0 })
  const { createSessionReadCache } = sessionReadCache()
  const cache = createSessionReadCache({ group: 'images', maxAgeMs: 60_000, maxEntries: 2, maxBytes: 4, size: value => value.length })
  let calls = 0
  const read = key => cache.read(key, async () => { calls++; return 'abc' })
  await Promise.all(Array.from({ length: 50 }, () => read('a')))
  assert.equal(calls, 1)
  await read('a')
  assert.equal(calls, 1)
  await read('b') // Each fits; both together exceed the byte budget.
  await read('a')
  assert.equal(calls, 3)
  t.mock.timers.tick(60_001)
  await read('a')
  assert.equal(calls, 4)
  await assert.rejects(cache.read('error', async () => { throw Error('offline') }), /offline/)
  assert.equal(await cache.read('error', async () => 'ok'), 'ok')
})

test('one cancelled reader leaves transport alive; the last cancellation aborts it', async () => {
  const { createSessionReadCache } = sessionReadCache()
  const cache = createSessionReadCache({ group: 'images', maxAgeMs: 60_000, maxEntries: 2 })
  const response = deferred()
  let transport
  const load = signal => { transport = signal; return response.promise }
  const one = new AbortController(), two = new AbortController()
  const first = cache.read('a', load, one.signal)
  const second = cache.read('a', load, two.signal)
  await setImmediate()
  const rejectedFirst = assert.rejects(first, { name: 'AbortError' })
  one.abort()
  await rejectedFirst
  assert.equal(transport.aborted, false)
  const rejectedSecond = assert.rejects(second, { name: 'AbortError' })
  two.abort()
  await rejectedSecond
  assert.equal(transport.aborted, true)
  response.resolve('old')
  await setImmediate()
  assert.equal(await cache.read('a', async () => 'new'), 'new')
})

test('session changes and mutations invalidate both endpoint caches and reject late responses', async () => {
  const window = new EventTarget()
  const { createSessionReadCache, invalidateSessionReads } = sessionReadCache(window)
  const options = { group: 'avatar', maxAgeMs: 60_000, maxEntries: 3 }
  const chat = createSessionReadCache(options), admin = createSessionReadCache(options)
  assert.equal(await chat.read('7', async () => 'chat'), 'chat')
  assert.equal(await admin.read('7', async () => 'admin'), 'admin')
  await admin.read('8', async () => 'unrelated')
  const unrelated = admin.read('8', async () => 'unneeded')
  invalidateSessionReads('avatar', '7')
  assert.equal(await unrelated, 'unrelated')
  assert.equal(await chat.read('7', async () => 'chat-new'), 'chat-new')
  const response = deferred()
  const pending = admin.read('7', () => response.promise)
  await setImmediate()
  const rejected = assert.rejects(pending, { name: 'AbortError' })
  window.dispatchEvent(new Event('auth'))
  await rejected
  response.resolve('stale')
  await setImmediate()
  assert.equal(await admin.read('7', async () => 'new-session'), 'new-session')
  assert.equal(await chat.read('7', async () => 'new-session-chat'), 'new-session-chat')
  const cached = chat.read('7', async () => 'unneeded')
  const cancelledHit = assert.rejects(cached, { name: 'AbortError' })
  window.dispatchEvent(new Event('auth'))
  await cancelledHit
})

test('zero freshness shares only concurrent catalogues and partitions scopes', async () => {
  const { createSessionReadCache } = sessionReadCache()
  const cache = createSessionReadCache({ group: 'catalogue', maxAgeMs: 0, maxEntries: 0 })
  let calls = 0
  const load = async () => ++calls
  assert.deepEqual(await Promise.all([cache.read('management', load), cache.read('management', load), cache.read('teams', load)]), [1, 1, 2])
  assert.equal(await cache.read('management', load), 3)
})

test('token renewal keeps a pending read alive while switching identity discards its cache', async () => {
  const window = new EventTarget()
  const { createSessionReadCache } = sessionReadCache(window)
  let generation = 'one'
  const cache = createSessionReadCache({ group: 'catalogue', sessionKey: () => generation, maxAgeMs: 60_000, maxEntries: 1 })
  const response = deferred()
  const read = cache.read('all', () => response.promise)
  await setImmediate()
  window.dispatchEvent(new Event('auth'))
  response.resolve('renewed')
  assert.equal(await read, 'renewed')
  assert.equal(await cache.read('all', async () => 'unneeded'), 'renewed')
  generation = 'two'
  window.dispatchEvent(new Event('auth'))
  assert.equal(await cache.read('all', async () => 'new identity'), 'new identity')
  generation = 'changed in another tab'
  assert.equal(await cache.read('all', async () => 'other tab'), 'other tab')
  const hit = cache.read('all', async () => 'unneeded')
  generation = 'changed before cached read completes'
  await assert.rejects(hit, { name: 'AbortError' })
})
