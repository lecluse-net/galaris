import assert from 'node:assert/strict'
import { cp, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

test('type-check and build reject errors in application, bridges and Vite configuration', async () => {
  const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const directory = await mkdtemp(path.join(tmpdir(), 'galaris-typecheck-'))
  try {
    await cp(source, directory, {
      recursive: true,
      filter: entry => !['node_modules', 'dist', '.git'].includes(path.basename(entry)),
    })
    await symlink(path.join(source, 'node_modules'), path.join(directory, 'node_modules'))
    for (const location of ['app', 'bridge']) {
      const probe = path.join(directory, location, 'typecheck_canary.ts')
      await writeFile(probe, 'export const typecheckCanary: number = "must fail"\n')
      for (const command of ['type-check', 'build']) {
        const result = spawnSync('npm', ['run', command], { cwd: directory, encoding: 'utf8', timeout: 60_000 })
        assert.equal(result.status, 2, result.stdout + result.stderr)
        assert.match(result.stdout, /typecheck_canary\.ts.*TS2322/)
      }
      await rm(probe)
    }
    await writeFile(path.join(directory, 'vite.config.ts'), 'export const typecheckCanary: number = "must fail"\n', { flag: 'a' })
    const result = spawnSync('npm', ['run', 'type-check'], { cwd: directory, encoding: 'utf8', timeout: 60_000 })
    assert.equal(result.status, 2, result.stdout + result.stderr)
    assert.match(result.stdout, /vite\.config\.ts.*TS2322/)
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
