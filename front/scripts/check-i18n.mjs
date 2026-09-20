import { readdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import ts from 'typescript'
import { validateCatalogSyntax } from './catalog-syntax.mjs'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

async function findModuleCatalogs(directory) {
  const result = []
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name)
    if (entry.isDirectory()) {
      result.push(...await findModuleCatalogs(entryPath))
    } else if (entry.name === 'i18n.ts') {
      result.push(entryPath)
    }
  }
  return result
}

async function loadTypeScriptDefault(filePath) {
  const source = await readFile(filePath, 'utf8')
  validateCatalogSyntax(source, filePath)
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filePath,
  }).outputText
  const loaded = { exports: {} }
  new Function('module', 'exports', output)(loaded, loaded.exports)
  return loaded.exports.default
}

function flatten(value, prefix = '', result = new Map()) {
  if (Array.isArray(value)) {
    value.forEach((child, index) => flatten(child, `${prefix}.${index}`, result))
  } else if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      flatten(child, prefix ? `${prefix}.${key}` : key, result)
    }
  } else {
    result.set(prefix, value)
  }
  return result
}

function placeholders(value) {
  if (typeof value !== 'string') return []
  return [...value.matchAll(/\{([A-Za-z_][A-Za-z0-9_.]*)\}/g)]
    .map(match => match[1])
    .sort()
}

function compareCatalogs(label, english, french, errors) {
  const en = flatten(english)
  const fr = flatten(french)
  const allKeys = new Set([...en.keys(), ...fr.keys()])

  for (const key of [...allKeys].sort()) {
    if (!en.has(key)) errors.push(`${label}: missing English key ${key}`)
    if (!fr.has(key)) errors.push(`${label}: missing French key ${key}`)
    if (!en.has(key) || !fr.has(key)) continue

    const enValue = en.get(key)
    const frValue = fr.get(key)
    if (typeof enValue !== 'string' || enValue.trim() === '') {
      errors.push(`${label}: English value ${key} is not a non-empty string`)
    }
    if (typeof frValue !== 'string' || frValue.trim() === '') {
      errors.push(`${label}: French value ${key} is not a non-empty string`)
    }
    if (placeholders(enValue).join('\0') !== placeholders(frValue).join('\0')) {
      errors.push(`${label}: placeholder mismatch for ${key}`)
    }
  }

  return allKeys.size
}

function compareChineseCatalog(label, english, chinese, errors, requireComplete = false) {
  const en = flatten(english)
  const zh = flatten(chinese)
  if (requireComplete) {
    for (const key of en.keys()) {
      if (!zh.has(key)) errors.push(`${label}: missing Chinese key ${key}`)
    }
  }
  for (const [key, value] of zh) {
    if (!en.has(key)) {
      errors.push(`${label}: unknown Chinese key ${key}`)
      continue
    }
    if (typeof value !== 'string' || value.trim() === '') {
      errors.push(`${label}: Chinese value ${key} is not a non-empty string`)
    }
    if (placeholders(en.get(key)).join('\0') !== placeholders(value).join('\0')) {
      errors.push(`${label}: Chinese placeholder mismatch for ${key}`)
    }
  }
  return zh.size
}

const errors = []
let checkedKeys = 0
let checkedChineseKeys = 0
const translatedKeys = { en: new Set(), fr: new Set() }
const modulePaths = [
  ...await findModuleCatalogs(path.join(frontendRoot, 'app')),
  ...await findModuleCatalogs(path.join(frontendRoot, 'bridge')),
  ...await findModuleCatalogs(path.join(frontendRoot, 'core')),
].sort()

for (const filePath of modulePaths) {
  const catalog = await loadTypeScriptDefault(filePath)
  const label = path.relative(frontendRoot, filePath)
  if (!catalog?.en || !catalog?.fr) {
    errors.push(`${label}: catalog must export both en and fr`)
    continue
  }
  checkedKeys += compareCatalogs(label, catalog.en, catalog.fr, errors)
  if (!catalog.zh) {
    errors.push(`${label}: catalog must export zh`)
  } else {
    checkedChineseKeys += compareChineseCatalog(label, catalog.en, catalog.zh, errors, true)
  }
  for (const key of flatten(catalog.en).keys()) translatedKeys.en.add(key)
  for (const key of flatten(catalog.fr).keys()) translatedKeys.fr.add(key)
}

const baseEnPath = path.join(frontendRoot, 'core/i18n/locales/en.ts')
const baseFrPath = path.join(frontendRoot, 'core/i18n/locales/fr.ts')
const baseEn = await loadTypeScriptDefault(baseEnPath)
const baseFr = await loadTypeScriptDefault(baseFrPath)
checkedKeys += compareCatalogs(
  'core/i18n/locales',
  baseEn,
  baseFr,
  errors,
)
checkedChineseKeys += compareChineseCatalog(
  'core/i18n/locales',
  baseEn,
  await loadTypeScriptDefault(path.join(frontendRoot, 'core/i18n/locales/zh.ts')),
  errors,
  true,
)
for (const key of flatten(baseEn).keys()) translatedKeys.en.add(key)
for (const key of flatten(baseFr).keys()) translatedKeys.fr.add(key)

const privilegeDefinitions = await readFile(
  path.join(frontendRoot, 'core/authorize/definitions.ts'),
  'utf8',
)
for (const [, code] of privilegeDefinitions.matchAll(/^export const ([A-Z][A-Z0-9_]*) = '[A-Z][A-Z0-9_]*'$/gm)) {
  const key = `privilege.${code}`
  if (!translatedKeys.en.has(key)) errors.push(`missing English key ${key}`)
  if (!translatedKeys.fr.has(key)) errors.push(`missing French key ${key}`)
}
if (!translatedKeys.en.has('role.admin')) errors.push('missing English key role.admin')
if (!translatedKeys.fr.has('role.admin')) errors.push('missing French key role.admin')

if (errors.length > 0) {
  for (const error of errors) console.error(error)
  process.exitCode = 1
} else {
  console.log(`i18n catalogs checked: ${checkedKeys} English/French pairs and ${checkedChineseKeys} Chinese messages.`)
}
