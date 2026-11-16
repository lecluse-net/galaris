import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
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
  const report = (...args) => execFileSync(process.execPath, [
    fileURLToPath(new URL('./report-build.mjs', import.meta.url)), directory, ...args,
  ], { encoding: 'utf8', stdio: 'pipe' })
  await writeFile(join(directory, 'manifest.webmanifest'), JSON.stringify(pwa))
  assert.equal(JSON.parse(report()).metric, 'frontend_build_bytes')
  assert.equal(JSON.parse(report('--check-budgets')).metric, 'frontend_build_bytes')
  assert.throws(() => report('--check-budget'), /Unknown option/)
  for (const field of Object.keys(pwa)) {
    for (const value of [undefined, '']) {
      await writeFile(join(directory, 'manifest.webmanifest'), JSON.stringify({ ...pwa, [field]: value }))
      for (const args of [[], ['--check-budgets']]) {
        assert.throws(() => report(...args), new RegExp(`Installed PWA requires.*${field}`))
      }
    }
  }
})

test('startup and full chat journeys count shared assets once regardless of chunk placement', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'locale-build-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  await mkdir(join(directory, '.vite'))
  const files = { 'index.js': 'entry', 'shared.js': 'shared', 'shared.css': 'styles', 'chat.js': 'chat', 'optional.js': 'optional view', 'fr.json': '{"hello":"Bonjour"}', 'zh.json': '{"hello":"你好"}' }
  for (const [name, value] of Object.entries(files)) await writeFile(join(directory, name), value)
  await mkdir(join(directory, 'fonts'))
  await writeFile(join(directory, 'fonts/synthetic.woff2'), Buffer.alloc(2048, 1))
  await writeFile(join(directory, 'public-image.png'), Buffer.alloc(512, 2))
  await writeFile(join(directory, 'manifest.webmanifest'), JSON.stringify({ theme_color: '#202020', background_color: '#202020' }))
  await writeFile(join(directory, '.vite/manifest.json'), JSON.stringify({
    'index.html': { file: 'index.js', isEntry: true, imports: ['shared'], css: ['shared.css'] },
    shared: { file: 'shared.js', css: ['shared.css'] },
    'app/chat/pages/index.vue': { file: 'chat.js', imports: ['shared'], dynamicImports: ['optional'] },
    optional: { file: 'optional.js' },
    'core/i18n/catalogs/fr.json': { file: 'fr.json' },
    'core/i18n/catalogs/zh.json': { file: 'zh.json' },
  }))
  const report = JSON.parse(execFileSync(process.execPath, [fileURLToPath(new URL('./report-build.mjs', import.meta.url)), directory], { encoding: 'utf8' }))
  const eagerBytes = files['index.js'].length + files['shared.js'].length + files['shared.css'].length
  assert.equal(report.eager.bytes, eagerBytes)
  assert.deepEqual(report.startup_by_locale.en, report.eager)
  assert.equal(report.route_additional.chat.bytes, files['chat.js'].length)
  assert.equal(report.route_additional.chat.gzip_bytes, gzipSync(files['chat.js']).length)
  assert.equal(report.route_total_by_locale.chat.en.bytes, eagerBytes + files['chat.js'].length)
  assert.deepEqual(report.packaged_assets.by_kind.fonts, { files: 1, bytes: 2048 })
  assert.deepEqual(report.packaged_assets.by_kind.images, { files: 1, bytes: 512 })
  assert.deepEqual(report.packaged_assets.largest[0], { file: 'fonts/synthetic.woff2', bytes: 2048 })
  for (const locale of ['fr', 'zh']) {
    const data = Buffer.from(files[`${locale}.json`])
    assert.equal(report.startup_by_locale[locale].bytes, eagerBytes + data.length)
    assert.equal(report.startup_by_locale[locale].gzip_bytes, report.eager.gzip_bytes + gzipSync(data).length)
    assert.equal(report.route_total_by_locale.chat[locale].bytes, eagerBytes + files['chat.js'].length + data.length)
  }
  const manifestPath = join(directory, '.vite/manifest.json')
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
  manifest['index.html'].imports = []
  manifest['index.html'].css = []
  await writeFile(manifestPath, JSON.stringify(manifest))
  const deferred = JSON.parse(execFileSync(process.execPath, [fileURLToPath(new URL('./report-build.mjs', import.meta.url)), directory, '--check-budgets'], { encoding: 'utf8' }))
  assert.ok(deferred.eager.bytes < report.eager.bytes)
  assert.ok(deferred.route_additional.chat.bytes > report.route_additional.chat.bytes)
  assert.deepEqual(deferred.route_total_by_locale, report.route_total_by_locale)
})

test('budget overruns warn during packaging and fail the explicit quality gate for every measured graph', async t => {
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
    fileURLToPath(new URL('./report-build.mjs', import.meta.url)), directory, '--check-budgets',
  ], { encoding: 'utf8', stdio: 'pipe' })
  for (const locale of ['en', 'fr', 'zh', 'chat']) {
    await t.test(locale, async () => {
      const manifest = { 'index.html': { file: 'index.js', isEntry: true } }
      await writeFile(join(directory, 'index.js'), locale === 'en' ? `export const text = ${JSON.stringify(noise)}` : 'export const text = "small"')
      if (locale === 'chat') {
        manifest['app/chat/pages/index.vue'] = { file: 'chat.js', imports: ['index.html'] }
        await writeFile(join(directory, 'chat.js'), `export const text = ${JSON.stringify(noise)}`)
      } else if (locale !== 'en') {
        manifest[`core/i18n/catalogs/${locale}.json`] = { file: `${locale}.json` }
        await writeFile(join(directory, `${locale}.json`), JSON.stringify({ text: noise }))
      }
      await writeFile(join(directory, '.vite/manifest.json'), JSON.stringify(manifest))
      const packaging = spawnSync(process.execPath, [
        fileURLToPath(new URL('./report-build.mjs', import.meta.url)), directory,
      ], { encoding: 'utf8' })
      assert.equal(packaging.status, 0, packaging.stderr)
      const measurements = JSON.parse(packaging.stdout)
      const measured = locale === 'chat' ? measurements.route_total_by_locale.chat.en : measurements.startup_by_locale[locale]
      const limit = locale === 'chat' ? measurements.route_code_gzip_limits.chat : measurements.startup_gzip_limits[locale]
      assert.ok(measured.gzip_bytes > limit)
      assert.match(packaging.stderr, new RegExp(`${locale} ${locale === 'chat' ? 'route code' : 'startup'} exceeds gzip budget`))
      assert.match(packaging.stderr, /npm run check:build-budgets/)
      assert.throws(report, new RegExp(`${locale} ${locale === 'chat' ? 'route code' : 'startup'} exceeds gzip budget`))
    })
  }
})
