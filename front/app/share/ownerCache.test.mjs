import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'
import { sessionReadCache } from '../../test-support/session-read-cache.mjs'

function setup() {
  const window = new EventTarget(), helpers = sessionReadCache(window)
  let generation = 'one', failure = false, delayed
  const calls = []
  const api = { get: async (url, options) => {
    calls.push({ url, options })
    if (failure) throw Error('offline')
    if (delayed) return delayed.promise
    const person = { kind: 'user', id: 1, label: generation, is_current_user: true }
    return { data: url.startsWith('/documents') ? { agents: [], users: [person] }
      : url.endsWith('/owner') ? { owner: person, options: [person], current_user_id: 1 } : [person] }
  } }
  const apiModule = { api, __esModule: true, default: api, AUTH_TOKEN_CHANGED_EVENT: 'auth', sessionGeneration: () => generation }
  const resources = loadTypescript(new URL('../../core/util/sessionResources.ts', import.meta.url), {
    '@/core/api': apiModule, './sessionReadCache': helpers, './previewQueue': helpers,
  }, { window })
  const shared = loadTypescript(new URL('./ownerCache.ts', import.meta.url), {
    '@/core/util/facade': { ...helpers, ...resources },
  })
  const dependencies = { '@/core/api': apiModule, '@/app/share/facade': shared,
    '@/core/util/facade': { thumbnailReady: () => assert.fail('An owner catalogue must not load thumbnails') } }
  const documents = loadTypescript(new URL('../document/services/documentService.ts', import.meta.url), dependencies).documentService
  const process = loadTypescript(new URL('../process/services/nativeProcessService.ts', import.meta.url), dependencies).nativeProcessService
  const dataset = loadTypescript(new URL('../dataset/services/datasetService.ts', import.meta.url), dependencies).datasetService
  return { calls, helpers, api,
    reads: { document: () => documents.listDocumentOwnerOptions(), process: () => process.ownerOptions(), dataset: () => dataset.owner('synthetic', 1) },
    documents, dataset,
    switchSession() { generation = 'two'; window.dispatchEvent(new Event('auth')) },
    fail(value) { failure = value }, delay() { delayed = deferred(); return delayed },
  }
}

for (const domain of ['document', 'process', 'dataset']) {
test(`${domain} owners share requests, isolate copies and expire after five minutes`, async t => {
  t.mock.timers.enable({ apis: ['Date'], now: 0 })
  const state = setup(), read = state.reads[domain]
  const copies = await Promise.all([read(), read(), read()])
  assert.equal(state.calls.length, 1, 'three concurrent openings need one request')
  const original = structuredClone(copies[0])
  const people = value => Array.isArray(value) ? value : value.users ?? value.options
  people(copies[0])[0].label = 'Local draft'
  assert.deepEqual(await read(), original)
  t.mock.timers.tick(299_999)
  await read()
  assert.equal(state.calls.length, 1, 'fresh openings reuse the catalogue')
  t.mock.timers.tick(2)
  await read()
  assert.equal(state.calls.length, 2, 'the next opening refreshes an expired catalogue')
  state.switchSession()
  assert.equal(people(await read())[0].label, 'two')
  assert.equal(state.calls.length, 3)
})
}

test('domains, searches, datasets and lock versions never share owner permissions', async () => {
  const state = setup()
  await Promise.all(Object.values(state.reads).map(read => read()))
  assert.equal(state.calls.length, 3)
  await state.documents.listDocumentOwnerOptions('another person')
  await state.dataset.owner('different', 1)
  await state.dataset.owner('synthetic', 2)
  assert.equal(state.calls.length, 6)
  state.helpers.invalidateSessionReads('agent-selection')
  await state.reads.document()
  assert.equal(state.calls.length, 7)
})

test('owner failures retry and obsolete session responses never populate the cache', async () => {
  const state = setup()
  state.fail(true)
  await assert.rejects(state.reads.process(), /offline/)
  state.fail(false)
  await state.reads.process()
  assert.equal(state.calls.length, 2)
  const delayed = state.delay()
  const pending = state.reads.document()
  const rejected = assert.rejects(pending, { name: 'AbortError' })
  state.switchSession()
  await rejected
  delayed.resolve({ data: { agents: [], users: [{ kind: 'user', id: 1, label: 'obsolete' }] } })
})
