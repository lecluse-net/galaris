import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { toolOrigin, toolMessageKey } = loadTypescript(new URL('./presentation.ts', import.meta.url), {})

test('bridge names do not turn administrator-owned Tools into Galaris Tools', () => {
  for (const code of ['n8n', 'nextcloud', 'nextcloud_talk', 'affine', 'messenger', 'matrix', 'telegram', 'whatsapp', 'one_bot', 'team-files']) {
    assert.equal(toolOrigin({ code, can_edit: true }), 'custom', code)
    assert.equal(toolMessageKey(code, 'label'), null, code)
    assert.equal(toolMessageKey(code, 'description'), null, code)
  }
})

test('Tool origin follows the backend ownership contract', () => {
  for (const code of ['galaris', 'file_sharing', 'browser', 'mail', 'lab']) {
    assert.equal(toolOrigin({ code, can_edit: false }), 'galaris', code)
  }
  assert.equal(toolOrigin({ code: 'browser', can_edit: true }), 'custom')
})
