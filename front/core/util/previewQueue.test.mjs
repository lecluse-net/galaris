import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate } from 'node:timers/promises'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'

test('previews yield before loading, limit concurrent work and discard cancelled queued work', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { queuePreview } = loadTypescript(new URL('./previewQueue.ts', import.meta.url), {})
  const first = deferred(), second = deferred()
  const cancelled = new AbortController()
  const started = []
  const one = queuePreview(() => { started.push(1); return first.promise }, new AbortController().signal)
  const two = queuePreview(() => { started.push(2); return second.promise }, new AbortController().signal)
  const three = queuePreview(async () => { started.push(3) }, cancelled.signal)
  const rejected = assert.rejects(three, { name: 'AbortError' })
  const four = queuePreview(async () => { started.push(4); return 'ready' }, new AbortController().signal)
  assert.deepEqual(started, [])
  t.mock.timers.tick(100)
  await setImmediate()
  assert.deepEqual(started, [1, 2])
  cancelled.abort()
  await rejected
  const failure = assert.rejects(one, /Renderer unavailable/)
  first.reject(Error('Renderer unavailable'))
  await failure
  await setImmediate()
  t.mock.timers.tick(100)
  assert.equal(await four, 'ready')
  assert.deepEqual(started, [1, 2, 4])
  second.resolve('ready')
  await two
})
