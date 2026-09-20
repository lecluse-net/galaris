import assert from 'node:assert/strict'
import test from 'node:test'
import { validateCatalogSyntax } from './catalog-syntax.mjs'

test('catalog syntax detects overwritten keys including quoted and nested keys', () => {
  assert.throws(() => validateCatalogSyntax('export default { fr: { a: "first", "a": "last" } }', 'catalog.ts'), /duplicate catalog key a/)
  assert.doesNotThrow(() => validateCatalogSyntax('export default { fr: { a: "fr" }, en: { a: "en" } }', 'catalog.ts'))
})
