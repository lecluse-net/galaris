// Measure the entry's eager dependency graph separately from optional chunks.
import { readFile } from 'node:fs/promises'
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
async function sizes(files) {
  const rows = await Promise.all([...files].map(async file => {
    const data = await readFile(resolve(directory, file))
    return { file, bytes: data.length, gzip_bytes: gzipSync(data).length }
  }))
  return {
    files: rows.length,
    bytes: rows.reduce((sum, row) => sum + row.bytes, 0),
    gzip_bytes: rows.reduce((sum, row) => sum + row.gzip_bytes, 0),
  }
}
const all = new Set(Object.values(manifest).flatMap(entry => [entry.file, ...(entry.css ?? [])]))
const startupByLocale = {}
const routeAdditional = {}
const routeGzipLimits = { chat: 200_000 }
for (const [name, key] of Object.entries({ chat: 'app/chat/pages/index.vue' })) {
  if (!manifest[key]) continue
  const files = new Set()
  visit(key, files)
  routeAdditional[name] = await sizes(new Set([...files].filter(file => !eager.has(file))))
}
// Leave room above the measured baseline while rejecting accidental eager views.
const startupGzipLimits = { en: 460_000, fr: 600_000, zh: 600_000 }
for (const locale of ['en', 'fr', 'zh']) {
  const files = new Set(eager)
  const key = `core/i18n/catalogs/${locale}.json`
  if (manifest[key]) visit(key, files)
  startupByLocale[locale] = await sizes(files)
}
console.log(JSON.stringify({
  metric: 'frontend_build_bytes',
  eager: await sizes(eager), all: await sizes(all),
  startup_by_locale: startupByLocale,
  startup_gzip_limits: startupGzipLimits,
  route_additional: routeAdditional,
  route_gzip_limits: routeGzipLimits,
  note: 'Static imports and CSS; startup_by_locale also includes the selected language. Excludes other dynamic imports, fonts, API traffic and PWA precache downloads. Gzip is measured per file.',
}, null, 2))
const overruns = []
for (const [locale, limit] of Object.entries(startupGzipLimits)) {
  const measured = startupByLocale[locale].gzip_bytes
  if (measured > limit) overruns.push(`${locale} startup exceeds gzip budget: ${measured} > ${limit} bytes`)
}
for (const [route, measurement] of Object.entries(routeAdditional)) {
  const limit = routeGzipLimits[route]
  if (measurement.gzip_bytes > limit) overruns.push(`${route} route exceeds gzip budget: ${measurement.gzip_bytes} > ${limit} bytes`)
}
// Performance regressions belong in the quality gate, not the installation path.
// Invalid or missing build artifacts still fail above in both modes.
if (values['check-budgets']) assert.equal(overruns.length, 0, overruns.join('\n'))
else if (overruns.length) console.warn(`Frontend performance warning:\n${overruns.join('\n')}\nRun npm run check:build-budgets to enforce these budgets in quality checks.`)
