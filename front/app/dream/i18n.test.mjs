import assert from 'node:assert/strict'
import test from 'node:test'
import dreamCatalog from './i18n.ts'
import paramsCatalog from '../../core/params/i18n.ts'

test('the Chinese locale translates the visible Dream product name', () => {
  assert.equal(dreamCatalog.zh.nav.dream, '梦境')
  assert.equal(paramsCatalog.zh.configuration.tabs.dream, '梦境')
  assert.doesNotMatch(JSON.stringify(dreamCatalog.zh), /\bDream\b/)
  assert.doesNotMatch(JSON.stringify(paramsCatalog.zh), /\bDream\b/)
})
