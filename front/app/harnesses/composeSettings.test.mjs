import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

test('managed containers retain the shared YAML Compose preference', () => {
  const { managedComposeFields } = loadTypescript(new URL('./managedSettings.ts', import.meta.url), {})
  assert.deepEqual(managedComposeFields.map(({ name, input, codeLanguage }) => ({ name, input, codeLanguage })), [
    { name: 'harness.default.compose', input: 'code', codeLanguage: 'yaml' },
  ])
})
