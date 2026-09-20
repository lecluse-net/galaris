import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

test('public navigation exposes legal and license destinations and no obsolete About route', () => {
  const navigation = loadTypescript(new URL('./navigation.ts', import.meta.url), { '@/core/authorize': { privileges: {} } }).default
  assert.equal(existsSync(new URL('./pages/about.vue', import.meta.url)), false)
  const destinations = value => Object.values(value).flatMap(node => [...(node.to ? [node.to] : []), ...destinations(node.children ?? {})])
  assert.deepEqual(destinations(navigation.pageFooter.children), ['/legal', '/license'])
  assert.ok(!destinations(navigation).includes('/about'))
})
