// Measure the entry's eager dependency graph separately from optional chunks.
import { readFile, readdir, stat } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'
import assert from 'node:assert/strict'
import { parseArgs } from 'node:util'

const { values, positionals } = parseArgs({
  options: { 'check-budgets': { type: 'boolean', default: false } },
  allowPositionals: true,
})
assert.ok(positionals.length <= 1, 'Expected at most one build directory')
const directory = resolve(positionals[0] ?? 'dist')
// Installed Android windows may retain their manifest colours independently of
// the live page. Keep these hints explicit instead of silently using defaults.
const pwa = JSON.parse(await readFile(resolve(directory, 'manifest.webmanifest'), 'utf8'))
for (const field of ['theme_color', 'background_color']) {
  assert.equal(typeof pwa[field], 'string', `Installed PWA requires an explicit ${field}`)
  assert.ok(pwa[field].trim(), `Installed PWA requires a nonempty ${field}`)
}
const manifest = JSON.parse(await readFile(resolve(directory, '.vite/manifest.json'), 'utf8'))
const eager = new Set()
function visit(key, files, visited = new Set()) {
  if (visited.has(key)) return
  visited.add(key)
  const entry = manifest[key]
  files.add(entry.file)
  for (const css of entry.css ?? []) files.add(css)
  for (const dependency of entry.imports ?? []) visit(dependency, files, visited)
}
for (const [key, entry] of Object.entries(manifest)) if (entry.isEntry) visit(key, eager)
const measuredFiles = new Map()
function measure(file) {
  if (!measuredFiles.has(file)) measuredFiles.set(file, readFile(resolve(directory, file)).then(data => (
    { file, bytes: data.length, gzip_bytes: gzipSync(data).length }
  )))
  return measuredFiles.get(file)
}
async function sizes(files) {
  const rows = await Promise.all([...files].map(measure))
  return {
    files: rows.length,
    bytes: rows.reduce((sum, row) => sum + row.bytes, 0),
    gzip_bytes: rows.reduce((sum, row) => sum + row.gzip_bytes, 0),
  }
}
const all = new Set(Object.values(manifest).flatMap(entry => [entry.file, ...(entry.css ?? [])]))
const startupByLocale = {}
const routeAdditional = {}
const routeTotalByLocale = {}
// The chat journey includes the shell: keep the existing combined allowance
// (460k initial code + 200k route code), independent of chunk placement.
// Locale JSON is measured separately and remains bounded by startup budgets.
const routeCodeGzipLimits = { chat: 660_000 }
for (const [name, key] of Object.entries({ chat: 'app/chat/pages/index.vue' })) {
  if (!manifest[key]) continue
  const files = new Set()
  visit(key, files)
  routeAdditional[name] = await sizes(new Set([...files].filter(file => !eager.has(file))))
  routeTotalByLocale[name] = {}
  for (const locale of ['en', 'fr', 'zh']) {
    const combined = new Set([...eager, ...files])
    const catalog = `core/i18n/catalogs/${locale}.json`
    if (manifest[catalog]) visit(catalog, combined)
    routeTotalByLocale[name][locale] = await sizes(combined)
  }
}
// Leave room above the measured baseline while rejecting accidental eager views.
const startupGzipLimits = { en: 460_000, fr: 600_000, zh: 600_000 }
for (const locale of ['en', 'fr', 'zh']) {
  const files = new Set(eager)
  const key = `core/i18n/catalogs/${locale}.json`
  if (manifest[key]) visit(key, files)
  startupByLocale[locale] = await sizes(files)
}
// Inventory all packaged files, including fonts and public assets omitted from
// Vite's JS/CSS graph. This is disk size, not a promise of network transfer size.
const packaged = (await Promise.all((await readdir(directory, { recursive: true }))
  .filter(file => !file.startsWith('.vite/'))
  .map(async file => ({ file, info: await stat(resolve(directory, file)) }))))
  .filter(({ info }) => info.isFile())
  .map(({ file, info }) => ({ file, bytes: info.size }))
const assetKinds = {}
for (const { file, bytes } of packaged) {
  const kind = /\.(?:woff2?|ttf|otf)$/.test(file) ? 'fonts' : file.endsWith('.js') ? 'js'
    : file.endsWith('.css') ? 'css' : file.endsWith('.json') ? 'json'
      : /\.(?:png|jpe?g|svg|ico|webp)$/.test(file) ? 'images' : 'other'
  const group = assetKinds[kind] ??= { files: 0, bytes: 0 }
  group.files++
  group.bytes += bytes
}
console.log(JSON.stringify({
  metric: 'frontend_build_bytes',
  eager: await sizes(eager), all: await sizes(all),
  startup_by_locale: startupByLocale,
  startup_gzip_limits: startupGzipLimits,
  route_additional: routeAdditional,
  route_total_by_locale: routeTotalByLocale,
  route_code_gzip_limits: routeCodeGzipLimits,
  packaged_assets: { by_kind: assetKinds, largest: packaged.sort((a, b) => b.bytes - a.bytes).slice(0, 10) },
  note: 'Static imports and CSS; startup_by_locale also includes the selected language. Excludes other dynamic imports, fonts, API traffic and PWA precache downloads. Gzip is measured per file.',
}, null, 2))
const overruns = []
for (const [locale, limit] of Object.entries(startupGzipLimits)) {
  const measured = startupByLocale[locale].gzip_bytes
  if (measured > limit) overruns.push(`${locale} startup exceeds gzip budget: ${measured} > ${limit} bytes`)
}
for (const [route, locales] of Object.entries(routeTotalByLocale)) {
  const measurement = locales.en
  const limit = routeCodeGzipLimits[route]
  if (measurement.gzip_bytes > limit) overruns.push(`${route} route code exceeds gzip budget: ${measurement.gzip_bytes} > ${limit} bytes`)
}
// Performance regressions belong in the quality gate, not the installation path.
// Invalid or missing build artifacts still fail above in both modes.
if (values['check-budgets']) assert.equal(overruns.length, 0, overruns.join('\n'))
else if (overruns.length) console.warn(`Frontend performance warning:\n${overruns.join('\n')}\nRun npm run check:build-budgets to enforce these budgets in quality checks.`)
