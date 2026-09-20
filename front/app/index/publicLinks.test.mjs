import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

// About now gathers the public credits; the former legal page is intentionally retired.
test('public navigation exposes About and the preserved license destination', () => {
  const navigation = loadTypescript(new URL('./navigation.ts', import.meta.url), { '@/core/authorize': { privileges: {} } }).default
  const destinations = value => Object.values(value).flatMap(node => [...(node.to ? [node.to] : []), ...destinations(node.children ?? {})])
  assert.deepEqual(destinations(navigation.pageFooter.children), ['/about', '/license'])
})
