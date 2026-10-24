import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { gzipSync } from 'node:zlib'

test('production build rejects missing native PWA colour hints', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'pwa-build-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  await mkdir(join(directory, '.vite'))
  await writeFile(join(directory, '.vite/manifest.json'), '{}')
  const pwa = { theme_color: '#202020', background_color: '#202020' }
  const report = () => execFileSync(process.execPath, [
    fileURLToPath(new URL('./report-build.mjs', import.meta.url)), directory,
  ], { encoding: 'utf8', stdio: 'pipe' })
  await writeFile(join(directory, 'manifest.webmanifest'), JSON.stringify(pwa))
  assert.equal(JSON.parse(report()).metric, 'frontend_build_bytes')
  for (const field of Object.keys(pwa)) {
    for (const value of [undefined, '']) {
      await writeFile(join(directory, 'manifest.webmanifest'), JSON.stringify({ ...pwa, [field]: value }))
      assert.throws(report, new RegExp(`Installed PWA requires.*${field}`))
    }
  }
})

test('startup measurement includes the selected JSON catalog and counts shared assets only once', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'locale-build-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  await mkdir(join(directory, '.vite'))
  const files = { 'index.js': 'entry', 'shared.js': 'shared', 'shared.css': 'styles', 'fr.json': '{"hello":"Bonjour"}', 'zh.json': '{"hello":"你好"}' }
  for (const [name, value] of Object.entries(files)) await writeFile(join(directory, name), value)
  await writeFile(join(directory, 'manifest.webmanifest'), JSON.stringify({ theme_color: '#202020', background_color: '#202020' }))
  await writeFile(join(directory, '.vite/manifest.json'), JSON.stringify({
    'index.html': { file: 'index.js', isEntry: true, imports: ['shared'], css: ['shared.css'] },
    shared: { file: 'shared.js', css: ['shared.css'] },
    'core/i18n/catalogs/fr.json': { file: 'fr.json' },
    'core/i18n/catalogs/zh.json': { file: 'zh.json' },
  }))
  const report = JSON.parse(execFileSync(process.execPath, [fileURLToPath(new URL('./report-build.mjs', import.meta.url)), directory], { encoding: 'utf8' }))
  const eagerBytes = files['index.js'].length + files['shared.js'].length + files['shared.css'].length
  assert.equal(report.eager.bytes, eagerBytes)
  assert.deepEqual(report.startup_by_locale.en, report.eager)
  for (const locale of ['fr', 'zh']) {
    const data = Buffer.from(files[`${locale}.json`])
    assert.equal(report.startup_by_locale[locale].bytes, eagerBytes + data.length)
    assert.equal(report.startup_by_locale[locale].gzip_bytes, report.eager.gzip_bytes + gzipSync(data).length)
  }
})

test('startup budgets reject eager code and each secondary language independently', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'startup-budget-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  await mkdir(join(directory, '.vite'))
  await writeFile(join(directory, 'manifest.webmanifest'), JSON.stringify({ theme_color: '#202020', background_color: '#202020' }))
  // Deterministic synthetic text whose compressed size exceeds every startup budget.
  let state = 123456789
  const noise = Array.from({ length: 900_000 }, () => {
    state ^= state << 13; state ^= state >>> 17; state ^= state << 5
    return 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'[state >>> 0 & 63]
  }).join('')
  const report = () => execFileSync(process.execPath, [
    fileURLToPath(new URL('./report-build.mjs', import.meta.url)), directory,
  ], { encoding: 'utf8', stdio: 'pipe' })
  for (const locale of ['en', 'fr', 'zh']) {
    await t.test(locale, async () => {
      const manifest = { 'index.html': { file: 'index.js', isEntry: true } }
      await writeFile(join(directory, 'index.js'), locale === 'en' ? `export const text = ${JSON.stringify(noise)}` : 'export const text = "small"')
      if (locale !== 'en') {
        manifest[`core/i18n/catalogs/${locale}.json`] = { file: `${locale}.json` }
        await writeFile(join(directory, `${locale}.json`), JSON.stringify({ text: noise }))
      }
      await writeFile(join(directory, '.vite/manifest.json'), JSON.stringify(manifest))
      assert.throws(report, new RegExp(`${locale} startup exceeds gzip budget`))
    })
  }
})
