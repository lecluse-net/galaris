import assert from 'node:assert/strict'
import test from 'node:test'
import { setTimeout } from 'node:timers/promises'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { deferred, loadTypescript } from '../../../test-support/load-typescript.mjs'

function setup() {
  const events = new EventTarget()
  let generation = 'first'
  const reads = [], writes = []
  const { useDocumentIcons } = loadTypescript(new URL('./documentIcons.ts', import.meta.url), {
    vue, pinia,
    '@/core/api': { AUTH_TOKEN_CHANGED_EVENT: 'token', sessionGeneration: () => generation },
    '../services/documentService': { documentService: {
      resolveDocumentIcons(ids, signal) { const result = deferred(); reads.push({ ids, signal, ...result }); return result.promise },
      saveDocumentIcon(id, icon) { const result = deferred(); writes.push({ id, icon, ...result }); return result.promise },
    } },
  }, { window: events })
  const store = useDocumentIcons(pinia.createPinia())
  return { store, reads, writes, token(next = generation, detail = 'renewed') {
    generation = next; events.dispatchEvent(new CustomEvent('token', { detail }))
  }, close() { store.$dispose() } }
}

test('token renewal retains cached icons, pending reads and writes without duplicate requests', async () => {
  const state = setup()
  try {
    state.store.ensure('cached'); state.store.ensure('cached')
    await setTimeout(5)
    state.reads[0].resolve({ cached: 'emoji:1F680' })
    await setTimeout(0)
    state.store.ensure('pending')
    await setTimeout(5)
    const write = state.store.save('cached', null)
    const session = state.store.session
    state.token()
    assert.equal(state.store.session, session)
    assert.equal(state.store.icons.cached, 'emoji:1F680')
    assert.equal(state.store.saving.cached, true)
    state.store.ensure('cached'); state.store.ensure('pending')
    state.reads[1].resolve({ pending: 'emoji:1F600' })
    state.writes[0].resolve({ icon: null })
    assert.equal(await write, true)
    await setTimeout(5)
    assert.equal(state.reads.length, 2)
    assert.equal(state.store.icons.pending, 'emoji:1F600')
    assert.equal(state.store.icons.cached, null)
    assert.equal(state.store.saving.cached, false)
  } finally { state.close() }
})

test('icons batch at 500, retry failed reads and retain a saved choice over late reads', async () => {
  const state = setup()
  try {
    for (let index = 0; index < 501; index++) state.store.ensure(`doc-${index}`)
    await setTimeout(5)
    assert.equal(state.reads[0].ids.length, 500)
    const write = state.store.save('doc-0', 'emoji:1F680')
    state.writes[0].resolve({ icon: 'emoji:1F680' })
    await write
    state.reads[0].resolve({ 'doc-0': null })
    await setTimeout(0)
    assert.deepEqual(state.reads[1].ids, ['doc-500'])
    state.reads[1].reject(new Error('Synthetic failure'))
    await setTimeout(0)
    assert.equal(state.store.icons['doc-0'], 'emoji:1F680')
    assert.equal(state.store.errors['doc-500'], true)
    state.store.ensure('doc-500')
    await setTimeout(5)
    state.reads[2].resolve({ 'doc-500': null })
    await setTimeout(0)
    assert.equal(state.store.icons['doc-500'], null)
    assert.equal(state.store.errors['doc-500'], false)
  } finally { state.close() }
})

for (const logout of [false, true]) test(`${logout ? 'logout' : 'a new session'} discards old icon reads and writes without blocking the new session`, async () => {
  const state = setup()
  try {
    state.store.ensure('doc')
    await setTimeout(5)
    const oldWrite = state.store.save('doc', 'emoji:1F680')
    state.token('second', logout ? null : 'other-account')
    assert.equal(state.reads[0].signal?.aborted, true)
    assert.deepEqual({ ...state.store.icons }, {})
    state.store.ensure('doc')
    await setTimeout(5)
    const currentWrite = state.store.save('doc', null)
    state.writes[1].resolve({ icon: null }); await currentWrite
    state.reads[1].resolve({ doc: 'emoji:1F600' })
    state.reads[0].resolve({ doc: 'emoji:1F680' })
    state.writes[0].resolve({ icon: 'emoji:1F680' })
    assert.equal(await oldWrite, false)
    await setTimeout(0)
    assert.equal(state.store.icons.doc, null)
    assert.equal(state.store.saving.doc, false)
  } finally { state.close() }
})
