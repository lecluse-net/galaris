import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { once } from 'node:events'
import test from 'node:test'
import axios from 'axios'
import { deferred, loadTypescript } from '../test-support/load-typescript.mjs'

// Exercise Axios/Fetch against a real HTTP peer that closes the connection.
async function setup(context, handler, navigator = { onLine: true }) {
  const requests = []
  const first = deferred()
  const backoff = deferred()
  const server = createServer((request, response) => {
    requests.push({ url: request.url, authorization: request.headers.authorization })
    handler(request, response, requests.length)
    first.resolve()
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  context.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve) }))
  const origin = `http://127.0.0.1:${server.address().port}`
  const storage = new Map([['access_token', 'account-a']])
  const transport = axios.create({ adapter: 'fetch' })
  const facade = {
    ...axios,
    create: options => {
      Object.assign(transport.defaults, options, { baseURL: `${origin}/api` })
      return transport
    },
    post: (url, data, config) => transport.post(new URL(url, origin).href, data, config),
  }
  const client = loadTypescript(new URL('./api.ts', import.meta.url), {
    axios: { __esModule: true, default: facade },
    './i18n': { i18n: { global: { t: (key, values) => values ? JSON.stringify(values) : key } } },
  }, {
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    window: { dispatchEvent() {}, location: { pathname: '/' } }, CustomEvent: class {}, navigator,
    setTimeout: (...args) => { const timer = setTimeout(...args); backoff.resolve(); return timer },
  })
  return { ...client, requests, first: first.promise, backoff: backoff.promise }
}

function success(response, value = { items: [], total: 0 }) {
  response.writeHead(200, { 'Content-Type': 'application/json' })
  response.end(JSON.stringify(value))
}

test('an opted-in read recovers after two connections close without a response', async context => {
  const client = await setup(context, (request, response, attempt) => {
    if (attempt < 3) request.socket.destroy()
    else success(response, { items: ['preserved message'], total: 1 })
  })
  const result = await client.api.get('/chat/rooms/synthetic/messages', {
    retryNetworkRead: true, params: { page: 2, agent_id: 7, history_cursor: 'synthetic-cursor' },
  })
  assert.deepEqual(result.data.items, ['preserved message'])
  assert.equal(client.requests.length, 3)
  assert.ok(client.requests.every(request => request.url === client.requests[0].url))
  assert.ok(client.requests.every(request => request.authorization === 'Bearer account-a'))
})

test('a lasting outage stops after three attempts and preserves the final diagnostic', async context => {
  const client = await setup(context, request => request.socket.destroy())
  await assert.rejects(client.api.get('/messages', { retryNetworkRead: true }), error => {
    assert.equal(error.code, 'ERR_NETWORK')
    assert.match(error.message, /GET \/api\/messages/)
    return true
  })
  assert.equal(client.requests.length, 3)
})

test('writes, authentication and ordinary reads are never replayed after a transport failure', async context => {
  const client = await setup(context, request => request.socket.destroy())
  for (const options of [
    { method: 'get', url: '/messages' },
    { method: 'get', url: '/auth/login', retryNetworkRead: true },
    ...['post', 'put', 'patch', 'delete'].map(method => ({ method, url: '/messages', retryNetworkRead: true })),
  ]) {
    const previous = client.requests.length
    await assert.rejects(client.api.request(options), { code: 'ERR_NETWORK' })
    assert.equal(client.requests.length, previous + 1)
  }
})

for (const status of [403, 404, 429, 500, 502, 503]) {
  test(`HTTP ${status} remains an explicit failure without a retry`, async context => {
    const client = await setup(context, (_request, response) => {
      response.writeHead(status, { 'Content-Type': 'application/json' })
      response.end(JSON.stringify({ detail: 'Synthetic refusal' }))
    })
    await assert.rejects(client.api.get('/messages', { retryNetworkRead: true }), error => error.response?.status === status)
    assert.equal(client.requests.length, 1)
  })
}

for (const action of ['abort', 'change session']) {
  test(`${action} prevents an interrupted read from being sent again`, async context => {
    const client = await setup(context, request => request.socket.destroy())
    const controller = new AbortController()
    const pending = client.api.get('/messages', { retryNetworkRead: true, signal: controller.signal })
    const rejected = assert.rejects(pending, error => client.isCancelledRequest(error))
    await client.first
    await client.backoff
    if (action === 'abort') controller.abort()
    else client.saveAccessToken('account-b')
    await rejected
    assert.equal(client.requests.length, 1)
  })
}

test('network recovery and session refresh share their original bounded budgets', async context => {
  let reads = 0
  const client = await setup(context, (request, response) => {
    if (request.url === '/api/auth/refresh') return success(response, { access_token: 'renewed' })
    reads++
    if (reads === 1) { response.writeHead(401); response.end(); return }
    if (reads === 2) { request.socket.destroy(); return }
    success(response)
  })
  await client.api.get('/messages', { retryNetworkRead: true })
  assert.equal(reads, 3)
  assert.equal(client.requests.filter(request => request.url === '/api/auth/refresh').length, 1)
  assert.equal(client.requests.at(-1).authorization, 'Bearer renewed')
})

test('an offline browser does not spend requests on automatic retries', async context => {
  const client = await setup(context, request => request.socket.destroy(), { onLine: false })
  await assert.rejects(client.api.get('/messages', { retryNetworkRead: true }), { code: 'ERR_NETWORK' })
  assert.equal(client.requests.length, 1)
})

test('authentication replay does not reset an already used network retry budget', async context => {
  let reads = 0
  const client = await setup(context, (request, response) => {
    if (request.url === '/api/auth/refresh') return success(response, { access_token: 'renewed' })
    reads++
    if (reads === 2) { response.writeHead(401); response.end(); return }
    request.socket.destroy()
  })
  await assert.rejects(client.api.get('/messages', { retryNetworkRead: true }), { code: 'ERR_NETWORK' })
  assert.equal(reads, 4)
  assert.equal(client.requests.filter(request => request.url === '/api/auth/refresh').length, 1)
})
