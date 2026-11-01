import { EventEmitter } from 'node:events'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { collectPageErrors } from './page-errors.mjs'

const url = 'http://localhost:8484/api/documents/synthetic'
function fixture(t) {
  let now = 1000
  t.mock.method(Date, 'now', () => now)
  const frame = {}
  const page = new EventEmitter()
  page.mainFrame = () => frame
  const observed = collectPageErrors(page)
  const request = (requestUrl = url, navigation = false) => ({
    url: () => requestUrl, isNavigationRequest: () => navigation, frame: () => frame,
  })
  const navigate = () => page.emit('request', request('http://localhost:8484/documents', true))
  const cors = (requestUrl = url) => {
    const error = new Error(`/${requestUrl.split('://')[1]} due to access control checks.`)
    error.name = `XMLHttpRequest cannot load ${requestUrl.split('://')[0]}`
    error.stack = `XMLHttpRequest cannot load ${requestUrl} due to access control checks.`
    page.emit('pageerror', error)
  }
  return { page, observed, request, navigate, cors, advance: milliseconds => { now += milliseconds } }
}

for (const timing of ['before', 'during']) test(`navigation interruption recognizes an observed API request started ${timing} navigation`, t => {
  const f = fixture(t)
  if (timing === 'before') f.page.emit('request', f.request())
  f.navigate()
  if (timing === 'during') f.page.emit('request', f.request())
  f.cors()
  assert.deepEqual(f.observed(), [])
})

test('real CORS and JavaScript errors remain visible during navigation', t => {
  const f = fixture(t)
  f.page.emit('request', f.request())
  f.navigate()
  f.cors('http://localhost:8484/api/documents/other')
  f.page.emit('pageerror', new Error('Synthetic JavaScript failure'))
  assert.equal(f.observed().length, 2)
})

test('an API request alone never excuses a native CORS failure', t => {
  const f = fixture(t)
  f.page.emit('request', f.request())
  f.cors()
  assert.equal(f.observed().length, 1)
})

test('a completed request cannot conceal a later CORS failure', t => {
  const f = fixture(t)
  const completed = f.request()
  f.page.emit('request', completed)
  f.page.emit('requestfinished', completed)
  f.navigate()
  f.cors()
  assert.equal(f.observed().length, 1)
})

test('an old interruption cannot conceal a later CORS failure', t => {
  const f = fixture(t)
  f.navigate()
  f.page.emit('request', f.request())
  f.advance(1000)
  f.cors()
  assert.equal(f.observed().length, 1)
})
