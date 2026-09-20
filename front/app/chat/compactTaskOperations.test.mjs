import assert from 'node:assert/strict'
import test from 'node:test'

import { compactStreamingTail } from './compactTaskOperations.ts'

test('streamed AI and thinking previews keep the moving tail', () => {
  const content = `EARLIEST STREAM CONTENT ${'middle '.repeat(30)}LATEST STREAM CONTENT`
  const preview = compactStreamingTail(content)

  assert.ok(preview.startsWith('...'))
  assert.ok(preview.endsWith('LATEST STREAM CONTENT'))
  assert.doesNotMatch(preview, /EARLIEST STREAM CONTENT/)
})

test('empty streamed content stays empty', () => {
  assert.equal(compactStreamingTail('   '), '')
})
