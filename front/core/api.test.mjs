import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { createI18n } from 'vue-i18n'
import { loadTypescript } from '../test-support/load-typescript.mjs'

const output = ts.transpileModule(readFileSync(new URL('./api.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function setup({ refreshError, requestError, refresh, locale = 'fr' } = {}) {
  const i18n = createI18n({ legacy: false, locale, messages: Object.fromEntries(
    ['fr', 'en', 'zh'].map(language => [language, loadTypescript(new URL(`./i18n/locales/${language}.ts`, import.meta.url)).default]),
  ) })
  const storage = new Map([['access_token', 'old'], ['user', 'user']])
  let rejectResponse
  let refreshes = 0
  let requests = 0
  const http = {
    interceptors: { request: { use() {} }, response: { use(ok, fail) { rejectResponse = fail } } },
    async request(config) {
      requests++
      assert.equal(config.headers.Authorization, 'Bearer renewed')
      if (requestError) throw requestError
      return { data: 'ok' }
    },
  }
  const axios = {
    create: () => http,
    isAxiosError: value => value?.isAxiosError === true,
    async post() {
      refreshes++
      if (refresh) return refresh()
      if (refreshError) throw refreshError
      return { data: { access_token: 'renewed' } }
    },
  }
  const exports = {}
  new Function('require', 'exports', 'localStorage', 'window', 'CustomEvent', output)(
    name => name === './i18n' ? { i18n } : ({ __esModule: true, default: axios }), exports,
    { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    { dispatchEvent() {}, location: { pathname: '/' } }, class {},
  )
  return {
    ...exports,
    storage,
    get refreshes() { return refreshes },
    get requests() { return requests },
    expiredRequest: () => rejectResponse({ response: { status: 401 }, config: { url: '/tasks', headers: {} } }),
    rejectRequest: error => rejectResponse(error),
  }
}

function failure(status) { return { isAxiosError: true, response: { status } } }

test('only cancelled or superseded requests are ignorable, transport failures remain errors', () => {
  const client = setup()
  assert.equal(client.isCancelledRequest(new client.SupersededSessionError()), true)
  assert.equal(client.isCancelledRequest({ isAxiosError: true, code: 'ERR_CANCELED' }), true)
  for (const code of ['ERR_NETWORK', 'ECONNABORTED', 'ETIMEDOUT']) {
    assert.equal(client.isCancelledRequest({ isAxiosError: true, code }), false)
  }
  assert.equal(client.isCancelledRequest(failure(503)), false)
  assert.equal(client.isCancelledRequest(new Error('Unexpected failure')), false)
})

for (const status of [403, 500]) {
  test(`a replayed request returning ${status} preserves the renewed session`, async () => {
    const requestError = failure(status)
    const client = setup({ requestError })
    await assert.rejects(client.expiredRequest(), error => error === requestError)
    assert.equal(client.storage.get('access_token'), 'renewed')
    assert.equal(client.storage.get('user'), 'user')
    assert.equal(client.requests, 1)
  })
}

test('concurrent expired requests share one refresh', async () => {
  const client = setup()
  await Promise.all([client.expiredRequest(), client.expiredRequest()])
  assert.equal(client.refreshes, 1)
  assert.equal(client.requests, 2)
})

function networkFailure(method = 'get') {
  return Object.assign(new Error('Network Error'), {
    isAxiosError: true, code: 'ERR_NETWORK',
    config: { method, baseURL: '/api', url: '/conversations/messages?search=private#secret', headers: {} },
  })
}

test('network failures expose the diagnostic and identify the request without private parameters', async () => {
  const client = setup()
  const error = networkFailure()
  await assert.rejects(client.rejectRequest(error), caught => caught === error)
  assert.match(error.message, /Aucune réponse HTTP exploitable/)
  assert.match(error.message, /ne précise pas la cause/)
  assert.match(error.message, /ERR_NETWORK/)
  assert.match(error.message, /Network Error/)
  assert.match(error.message, /GET \/api\/conversations\/messages/)
  assert.doesNotMatch(error.message, /private|secret|\?/)
  assert.equal(client.apiErrorDetail(error), error.message)
})

test('a failed write preserves its technical error and is not repeated automatically', async () => {
  const client = setup()
  const error = networkFailure('post')
  await assert.rejects(client.rejectRequest(error))
  assert.match(error.message, /POST \/api\/conversations\/messages/)
  assert.match(error.message, /ERR_NETWORK/)
  assert.equal(error.code, 'ERR_NETWORK')
  assert.equal(client.requests, 0)
})

test('timeouts are distinguished from missing responses', async () => {
  const client = setup()
  const error = Object.assign(networkFailure(), { code: 'ECONNABORTED' })
  error.config.timeout = 60_000
  await assert.rejects(client.rejectRequest(error))
  assert.match(error.message, /délai/)
  assert.match(error.message, /60 s/)
  assert.match(error.message, /ECONNABORTED/)
  assert.doesNotMatch(error.message, /Aucune réponse HTTP exploitable/)
})

test('HTTP failures retain server details and explain server errors without details', async () => {
  const client = setup()
  const error = Object.assign(networkFailure(), { response: { status: 502, statusText: 'Bad Gateway', data: '<html>Bad gateway</html>' } })
  await assert.rejects(client.rejectRequest(error))
  assert.match(error.message, /HTTP 502 Bad Gateway/)
  assert.match(error.message, /journaux/)
  assert.doesNotMatch(error.message, /<html>/)
  const validation = Object.assign(networkFailure(), { response: { status: 422, data: { detail: [{ loc: ['body', 'name'], msg: 'Required field' }] } } })
  await assert.rejects(client.rejectRequest(validation))
  assert.match(client.apiErrorDetail(validation), /body.name: Required field/)
  assert.match(client.apiErrorDetail(validation), /HTTP 422/)
})

test('a failed session renewal receives the same explicit network explanation', async () => {
  const error = networkFailure('post')
  error.config.url = '/api/auth/refresh'
  delete error.config.baseURL
  const client = setup({ refreshError: error })
  await assert.rejects(client.expiredRequest())
  assert.match(error.message, /POST \/api\/auth\/refresh/)
  assert.match(error.message, /ERR_NETWORK/)
  assert.equal(client.storage.get('access_token'), 'old')
})

test('network explanations follow the active language', async () => {
  const client = setup({ locale: 'en' })
  const error = networkFailure()
  await assert.rejects(client.rejectRequest(error))
  assert.match(error.message, /No usable HTTP response/)
})

test('the underlying cause and the response remain available to diagnostic consumers', async () => {
  const client = setup()
  const cause = new Error('Connection reset by peer')
  const error = Object.assign(networkFailure(), { cause })
  await assert.rejects(client.rejectRequest(error))
  assert.match(error.message, /Connection reset by peer/)
  assert.doesNotMatch(error.message, /ne précise pas la cause/)
  assert.equal(error.cause, cause)
  assert.equal(client.apiErrorDetail(error), error.message)
})

test('absolute request URLs omit credentials and query parameters', async () => {
  const client = setup()
  const error = networkFailure()
  error.config.url = 'https://user:password@example.test/api/tasks?token=secret'
  await assert.rejects(client.rejectRequest(error))
  assert.match(error.message, /GET \/api\/tasks/)
  assert.doesNotMatch(error.message, /password|token|secret|example.test/)
})

test('an authentication refusal clears the session', async () => {
  const client = setup({ refreshError: failure(401) })
  await assert.rejects(client.expiredRequest())
  assert.equal(client.storage.has('access_token'), false)
  assert.equal(client.storage.has('user'), false)
  assert.equal(client.requests, 0)
})

test('a transient refresh failure preserves the session for a later retry', async () => {
  const client = setup({ refreshError: failure(503) })
  await assert.rejects(client.expiredRequest())
  assert.equal(client.storage.get('access_token'), 'old')
  assert.equal(client.requests, 0)
})

for (const outcome of ['success', '401']) {
  test(`late refresh ${outcome} cannot replace or clear another account`, async () => {
    let finish
    const client = setup({ refresh: () => new Promise((resolve, reject) => {
      finish = () => outcome === 'success'
        ? resolve({ data: { access_token: 'account-A' } }) : reject(failure(401))
    }) })
    const request = client.expiredRequest()
    await new Promise(resolve => setImmediate(resolve))
    client.clearStoredSession()
    client.saveAccessToken('account-B')
    finish()
    await assert.rejects(request)
    assert.equal(client.storage.get('access_token'), 'account-B')
    assert.equal(client.requests, 0)
  })
}

test('a stuck logout hook is bounded and a throwing hook does not skip others', async () => {
  const client = setup()
  let called = false
  client.registerBeforeLogoutHook(() => { throw new Error('cleanup failed') })
  client.registerBeforeLogoutHook(async () => { called = true })
  client.registerBeforeLogoutHook(() => new Promise(() => {}))
  await client.runBeforeLogoutHooks()
  assert.equal(called, true)
})
