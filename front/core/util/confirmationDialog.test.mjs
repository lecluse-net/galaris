import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

test('confirmation callbacks observe async failures and preserve the native hide handle', async () => {
  let accepted, hidden = false
  const failures = []
  const native = { onOk(callback) { accepted = callback; return native }, hide() { hidden = true } }
  const { showConfirmationDialog } = loadTypescript(new URL('./confirmationDialog.ts', import.meta.url), {
    quasar: { Dialog: { create: () => native } }, './components/ConfirmationDialog.vue': {},
  }, { console: { error: (...values) => failures.push(values) } })
  const failure = Error('Synthetic action failure')
  const chain = showConfirmationDialog({ message: 'Synthetic confirmation' }).onOk(async () => { throw failure })
  accepted(); await Promise.resolve(); await Promise.resolve()
  assert.equal(failures[0][1], failure)
  chain.hide(); assert.equal(hidden, true)
})
