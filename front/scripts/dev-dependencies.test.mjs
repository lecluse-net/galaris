import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { optimizeDeps, resolveConfig } from 'vite'

test('the application dependency graph can be scanned on a cold development start', async () => {
  const cacheDir = await mkdtemp(path.join(tmpdir(), 'galaris-dev-dependencies-'))
  try {
    const config = await resolveConfig({
      root: fileURLToPath(new URL('..', import.meta.url)),
      cacheDir,
      logLevel: 'error',
    }, 'serve')
    const metadata = await optimizeDeps(config, true, true)
    assert.ok(metadata.optimized.vue, 'the application Vue dependency must be discovered')
  } finally {
    await rm(cacheDir, { recursive: true, force: true })
  }
})
