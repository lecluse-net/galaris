import assert from 'node:assert/strict'
import test from 'node:test'
import axios from 'axios'
import { deferred, loadTypescript } from '../test-support/load-typescript.mjs'

function setup() {
  const entered = deferred()
  const response = deferred()
  const storage = new Map([['access_token', 'test-token']])
  const transport = axios.create({
    adapter: 'fetch',
    env: {
      fetch: async request => {
        entered.resolve(request)
        return new Promise((resolve, reject) => {
          request.signal.addEventListener('abort', () => reject(request.signal.reason), { once: true })
          response.promise.then(resolve, reject)
        })
      },
    },
  })
  const facade = Object.assign((...args) => transport(...args), {
    ...axios,
    create: options => {
      Object.assign(transport.defaults, options, { baseURL: 'http://lab.test/api' })
      return transport
    },
    post: (...args) => transport.post(...args),
  })
  const loaded = loadTypescript(new URL('./api.ts', import.meta.url), {
    axios: { __esModule: true, default: facade },
    './i18n': { i18n: { global: { t: key => key } } },
  }, {
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    window: { dispatchEvent() {}, location: { pathname: '/' } },
    CustomEvent: class {},
  })
  const dependencies = { '@/core/api': { __esModule: true, default: loaded.api, api: loaded.api } }
  return {
    ...loaded, entered, response,
    workbench: loadTypescript(new URL('../app/lab/services/labWorkbenchService.ts', import.meta.url), dependencies).labWorkbenchService,
    memory: loadTypescript(new URL('../app/memory/services/memoryService.ts', import.meta.url), dependencies).memoryService,
    harness: loadTypescript(new URL('../app/harnesses/services/harnessService.ts', import.meta.url), dependencies).harnessService,
  }
}

const operations = {
  'benchmark analysis': client => client.workbench.analyze('dispatcher', 'synthetic-run', 'fr'),
  'document PDF': client => client.memory.exportDocumentPdf('synthetic-document', '<p>Test</p>', new AbortController().signal),
  'document dataset': client => client.memory.appDataset('synthetic-document', 1, 'test-app', 'rows', { operation: 'read' }, new AbortController().signal),
  'harness installation': client => client.harness.install(1, 'synthetic-harness'),
  'session renewal': client => client.refreshAccessToken(),
  'multipart upload': client => { const data = new FormData(); data.set('file', new Blob(['test']), 'test.txt'); return client.api.post('/files', data) },
}

for (const [name, operation] of Object.entries(operations)) {
  test(`${name} accepts a response after more than one hour`, async context => {
    context.mock.timers.enable({ apis: ['setTimeout'] })
    const client = setup()
    const pending = operation(client)
    // Observe rejections immediately, including the pre-fix timeout reproduction.
    const outcome = pending.then(value => ({ value }), error => ({ error }))
    const request = await client.entered.promise
    context.mock.timers.tick(3_600_001)
    const aborted = request.signal.aborted
    client.response.resolve(new Response(JSON.stringify({ access_token: 'renewed', analysis_markdown: 'Analysis' }), { headers: { 'Content-Type': 'application/json' } }))
    const result = await outcome
    assert.equal(aborted, false, 'Elapsed time must not abort the HTTP request')
    assert.equal(result.error, undefined)
    assert.ok(result.value)
  })
}

test('explicit cancellation still interrupts a waiting request', async () => {
  const client = setup()
  const controller = new AbortController()
  const pending = client.api.get('/memory/items', { signal: controller.signal })
  const rejected = assert.rejects(pending, error => client.isCancelledRequest(error))
  await client.entered.promise
  controller.abort()
  await rejected
})

test('a late response from the previous session is rejected', async () => {
  const client = setup()
  const pending = client.workbench.analyze('dispatcher', 'synthetic-run', 'fr')
  const rejected = assert.rejects(pending, error => error instanceof client.SupersededSessionError)
  await client.entered.promise
  client.invalidateSessionRequests()
  client.response.resolve(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
  await rejected
})
