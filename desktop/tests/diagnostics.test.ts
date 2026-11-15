import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { tmpdir } from 'node:os'
import { writeFailure } from '../src/diagnostics.ts'

test('local update failures preserve the original cause and code locations while redacting secrets', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'galaris-update-diagnostic-'))
  try {
    const cause = Object.assign(new Error('Download https://user:synthetic-password@example.test/update?token=synthetic-token#fragment failed'), { code: 'ERR_CHECKSUM' })
    const error = new Error('Installation failed: authorization=synthetic-header {"token":"synthetic-json-value"} Bearer synthetic+bearer/value==', { cause })
    writeFailure(directory, '0.3.1', 'update:download', error)
    const body = await readFile(path.join(directory, 'desktop-update.log'), 'utf8')
    assert.ok(!body.includes('synthetic-password'))
    assert.ok(!body.includes('synthetic-token'))
    assert.ok(!body.includes('synthetic-header'))
    assert.ok(!body.includes('synthetic-json-value'))
    assert.ok(!body.includes('synthetic+bearer/value'))
    const record = JSON.parse(body)
    assert.equal(record.stage, 'update:download')
    assert.equal(record.cause.code, 'ERR_CHECKSUM')
    assert.ok(record.stack.includes('diagnostics.test.ts'))
    assert.ok(record.cause.message.includes('https://example.test/update'))
    await writeFile(path.join(directory, 'desktop-update.log'), 'Synthetic history\n'.repeat(40_000))
    writeFailure(directory, '0.3.1', 'update:download', cause)
    assert.ok((await readFile(path.join(directory, 'desktop-update.log.1'), 'utf8')).startsWith('Synthetic history'))
    assert.equal(JSON.parse(await readFile(path.join(directory, 'desktop-update.log'), 'utf8')).code, 'ERR_CHECKSUM')
    const blocked = path.join(directory, 'not-a-directory')
    await writeFile(blocked, 'Synthetic disk failure')
    assert.throws(() => writeFailure(blocked, '0.3.1', 'update:download', cause))
  } finally { await rm(directory, { recursive: true, force: true }) }
})
