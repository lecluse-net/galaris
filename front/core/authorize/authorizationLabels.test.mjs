import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { localizedAuthorizeLabel } = loadTypescript(new URL('./presentation.ts', import.meta.url), {
  '@/core/i18n': { i18n: { global: { te: key => key === 'roles.admin', t: () => 'Administrator' } } },
})

test('authorization labels translate known keys, preserve free text and fall back to the code', () => {
  assert.equal(localizedAuthorizeLabel({ code: 'ADMIN', display_name: ' roles.admin ' }), 'Administrator')
  assert.equal(localizedAuthorizeLabel({ code: 'CUSTOM', display_name: ' My custom role ' }), 'My custom role')
  for (const display_name of ['', '  ', null, undefined]) assert.equal(localizedAuthorizeLabel({ code: 'FALLBACK', display_name }), 'FALLBACK')
})
