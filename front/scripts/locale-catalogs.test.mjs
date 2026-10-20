import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import ts from 'typescript'
import { selectCatalogLocale } from '../localeCatalogs.ts'
import { readLocaleCatalog } from '../catalogData.ts'
import { deepMergeMessages } from '../core/i18n/merge.ts'

function evaluate(file, source = readFileSync(file, 'utf8')) {
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const exports = {}
  new Function('exports', 'require', output)(exports, path => evaluate(join(dirname(file), path + '.ts')))
  return exports
}

function catalogs(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = join(directory, entry.name)
    return entry.isDirectory() ? catalogs(file) : entry.name === 'i18n.ts' ? [file] : []
  })
}

test('language selection preserves every shipped message, including imported and local constants', () => {
  for (const layer of ['app', 'bridge', 'core']) {
    for (const file of catalogs(fileURLToPath(new URL('../' + layer, import.meta.url)))) {
      const source = readFileSync(file, 'utf8')
      const full = evaluate(file, source).default
      for (const locale of ['en', 'fr', 'zh']) {
        const selected = evaluate(file, selectCatalogLocale(source, file, locale)).default
        assert.deepEqual(selected, full[locale], `${file}: ${locale}`)
      }
    }
  }
})

test('unsupported catalog shapes and missing locales fail explicitly', () => {
  assert.throws(() => selectCatalogLocale('export default { en: {} }', 'i18n.ts', 'fr'), /missing locale fr/)
  assert.throws(() => selectCatalogLocale('export default data', 'i18n.ts', 'en'), /must default-export an object/)
})

test('generated JSON preserves the complete merged catalogs and Chinese English fallback', () => {
  const root = fileURLToPath(new URL('..', import.meta.url))
  const files = ['app', 'core', 'bridge'].flatMap(layer => catalogs(join(root, layer))).sort()
  for (const locale of ['fr', 'zh']) {
    const expected = evaluate(join(root, `core/i18n/locales/${locale}.ts`)).default
    for (const file of files) {
      const full = evaluate(file).default
      if (locale === 'zh') deepMergeMessages(expected, full.en)
      deepMergeMessages(expected, full[locale])
    }
    assert.deepEqual(readLocaleCatalog(root, locale), expected)
  }
})
