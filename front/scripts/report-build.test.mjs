import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

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
