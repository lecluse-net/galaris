import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

for (const domain of ['chat', 'mail']) {
  test(`${domain} availability waits for grants and rejects a late response after revocation`, async () => {
    const code = domain === 'chat' ? 'CHAT_ACCESS' : 'MAIL_ACCESS'
    const store = vue.reactive({ loaded: false, codes: [], hasPrivilege: value => store.codes.includes(value), hasAnyPrivilege: codes => codes.some(code => store.codes.includes(code)) })
    const pending = []
    const read = () => { const response = deferred(); pending.push(response); return response.promise }
    let token = 'synthetic-session'
    const window = new EventTarget()
    const dependencies = {
      vue,
      pinia: { getActivePinia: () => ({}) },
      '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', getStoredAccessToken: () => token, api: { get: read } },
      '@/core/authorize': { privileges: { CHAT_ACCESS: 'CHAT_ACCESS', MAIL_ACCESS: 'MAIL_ACCESS' }, usePrivilegeStore: () => store },
      './services/mailService': { mailService: { status: read } },
    }
    const url = domain === 'chat' ? './availability.ts' : '../connection/availability.ts'
    const module = loadTypescript(new URL(url, import.meta.url), dependencies, { window })
    const visible = module[domain === 'chat' ? 'isChatNavigationVisible' : 'isMailNavigationVisible']
    visible()
    window.dispatchEvent(new Event('focus'))
    assert.equal(pending.length, 0)
    store.loaded = true
    assert.equal(pending.length, 0, 'A loaded role without the domain grant sends no request')
    store.codes = [code]
    assert.equal(pending.length, 1)
    store.codes = []
    pending[0].resolve({ data: { enabled: domain === 'mail' } })
    await vue.nextTick()
    assert.equal(visible(), domain === 'chat', 'Revocation invalidates the pending activation state')
    store.codes = [code]
    pending[1].resolve({ data: { enabled: true } })
    await vue.nextTick()
    assert.equal(visible(), true)
    token = null
    window.dispatchEvent(new Event('auth'))
    store.codes = []
    window.dispatchEvent(new Event('online'))
    assert.equal(pending.length, 2, 'Logout and focus recovery do not probe a protected endpoint')
  })
}
