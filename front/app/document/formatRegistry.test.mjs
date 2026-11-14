import assert from 'node:assert/strict'
import test from 'node:test'
import { registerFormat } from './formatRegistry.ts'

test('format contributions preserve native ownership and reject collisions and invalid versions', () => {
  const registry = new Map()
  const native = { code: 'text', provider: 'galaris', version: 1 }
  registerFormat(registry, native)
  const plugin = { code: 'example.outline', provider: 'example', version: 2 }
  registerFormat(registry, plugin)
  assert.equal(registry.get('text'), native)
  assert.equal(registry.get('example.outline'), plugin)
  for (const invalid of [{ ...plugin, code: 'text' }, { ...plugin, code: '../escape' },
    { ...plugin, code: 'dataset' }, { ...plugin, code: 'other', version: 0 },
    { ...plugin, code: 'other', version: 1.5 }]) {
    assert.throws(() => registerFormat(registry, invalid))
  }
  assert.equal(registry.size, 2)
})
