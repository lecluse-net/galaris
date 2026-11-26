import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'
import { sessionReadCache, sessionResources } from '../../test-support/session-read-cache.mjs'

function setup() {
  const cache = sessionReadCache(), reads = []
  const resources = sessionResources({ AUTH_TOKEN_CHANGED_EVENT: 'auth', sessionGeneration: () => 'synthetic-session' }, cache)
  const { topicService } = loadTypescript(new URL('./services/topicService.ts', import.meta.url), {
    '@/core/util/facade': { ...resources, invalidateSessionReads: cache.invalidateSessionReads },
    '@/core/api': { api: {
      get: async (_path, options) => {
        const ids = options.params.getAll('ids'); reads.push(ids)
        return { data: ids.map(id => ({ id, title: `Synthetic ${reads.length}: ${id}` })) }
      },
      post: async (_path, input) => ({ data: { ...input, id: 'synthetic-new' } }),
      put: async (_path, input) => ({ data: input }),
      delete: async () => {},
    } },
  })
  return { topicService, reads }
}

test('reference catalogues coalesce, expire and invalidate after every kind of topic mutation', async t => {
  t.mock.timers.enable({ apis: ['Date'], now: 0 })
  const { topicService, reads } = setup()
  const first = await Promise.all([topicService.refs(['b', 'a', 'a']), topicService.refs(['a', 'b'])])
  assert.deepEqual(first[0], first[1]); assert.equal(reads.length, 1)
  first[0][0].title = 'A consumer edit'
  assert.notEqual((await topicService.refs(['a', 'b']))[0].title, 'A consumer edit')
  t.mock.timers.tick(60_001)
  await topicService.refs(['a', 'b']); assert.equal(reads.length, 2)
  for (const mutate of [
    () => topicService.create({ title: 'Synthetic', keywords: [] }),
    () => topicService.update({ id: 'a', revision: 1 }, { title: 'Synthetic', keywords: [] }),
    () => topicService.remove('a'),
    () => topicService.merge('a', 'b'),
    () => topicService.split('a', { title: 'Synthetic', keywords: [], memory_item_ids: [] }),
  ]) {
    const count = reads.length
    await mutate(); await topicService.refs(['a', 'b'])
    assert.equal(reads.length, count + 1)
  }
})

test('more than 500 topic references are returned without exceeding the API batch limit', async () => {
  const { topicService, reads } = setup()
  const ids = Array.from({ length: 1201 }, (_, index) => `topic-${index}`)
  const result = await topicService.refs(ids)
  assert.deepEqual(new Set(result.map(item => item.id)), new Set(ids))
  assert.deepEqual(reads.map(batch => batch.length), [500, 500, 201])
})
