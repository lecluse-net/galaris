import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'

function setup() {
  const agent = vue.reactive({ id: 1, code: 'synthetic-a' }), active = vue.ref(true), reads = [], creates = [], deletes = [], notifications = []
  const window = new EventTarget(); window.location = { origin: 'https://synthetic.invalid' }
  let dispose, confirm, session = 'first'
  const { useAgentMcp } = loadTypescript(new URL('./composables/useAgentMcp.ts', import.meta.url), {
    vue: { ...vue, onBeforeUnmount: callback => { dispose = callback } },
    'vue-i18n': { useI18n: () => ({ t: key => key, locale: vue.ref('en') }) },
    quasar: { useQuasar: () => ({ notify: value => notifications.push(value) }) },
    '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'auth', sessionGeneration: () => session },
    '@/core/util/facade': { showConfirmationDialog: () => ({ onOk: callback => { confirm = callback } }) },
    '../services/mcpTokenService': { mcpTokenService: {
      listTokens: id => { const request = deferred(); reads.push({ id, ...request }); return request.promise },
      createToken: id => { const request = deferred(); creates.push({ id, ...request }); return request.promise },
      deleteToken: async (agentId, tokenId) => { deletes.push({ agentId, tokenId }) },
    } },
  }, { window })
  const scope = vue.effectScope()
  const state = scope.run(() => useAgentMcp(() => agent, () => true, () => active.value))
  return { state, agent, active, reads, creates, deletes, notifications, confirm: () => confirm(),
    changeSession() { session = 'second'; window.dispatchEvent(new Event('auth')) },
    stop() { dispose(); scope.stop() } }
}

test('MCP list reads and confirmation callbacks stay with their edited agent', async () => {
  const fixture = setup(), { state, agent, reads } = fixture
  const old = state.loadMcpTokens()
  agent.id = 2
  const current = state.loadMcpTokens()
  reads[1].resolve({ data: [{ id: 22, agent_id: 2 }] }); await current
  reads[0].resolve({ data: [{ id: 11, agent_id: 1 }] }); await old
  assert.equal(state.mcpTokens.value[0].id, 22); assert.equal(state.mcpTokensLoading.value, false)
  state.deleteMcpToken({ id: 22 }); agent.id = 3
  await fixture.confirm()
  assert.deepEqual(fixture.deletes, [])
  fixture.stop()
})

test('closing or switching session during token creation never reveals old credentials', async () => {
  for (const close of [fixture => { fixture.active.value = false }, fixture => fixture.changeSession()]) {
    const fixture = setup(), { state, creates } = fixture
    const saving = state.confirmCreateMcpToken()
    close(fixture)
    creates[0].resolve({ data: { token: 'synthetic-once-only-token' } }); await saving
    assert.equal(state.newMcpTokenValue.value, ''); assert.equal(state.showNewMcpTokenDialog.value, false)
    assert.equal(state.mcpTokensLoading.value, false)
    fixture.stop()
  }
})
