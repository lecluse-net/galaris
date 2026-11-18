import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { externalURL, partitionFor, sameOrigin, serverOrigin } from '../src/policy.ts'
import { readServer, writeServer } from '../src/preferences.ts'
import messages from '../renderer/messages.json' with { type: 'json' }
import { readShellLayout, shellMessage } from '../src/shell.ts'

test('server selection requires a bare HTTPS origin; HTTP is limited to development loopback', () => {
  assert.equal(serverOrigin(' https://example.test:8443/ '), 'https://example.test:8443')
  for (const value of ['http://example.test', 'https://u:p@example.test', 'https://example.test/a', 'https://example.test/?token=secret', 'https://example.test/#a', 'file:///tmp/a', 'javascript:alert(1)', '', null]) {
    assert.throws(() => serverOrigin(value))
  }
  assert.throws(() => serverOrigin('http://127.0.0.1'))
  assert.equal(serverOrigin('http://127.0.0.1:8000', true), 'http://127.0.0.1:8000')
  assert.throws(() => serverOrigin('http://127.0.0.1.example.test', true))
})

test('sessions isolate server origins, including ports, and reopen deterministically', () => {
  const origin = serverOrigin('https://example.test')
  assert.equal(partitionFor(origin), partitionFor(serverOrigin('https://EXAMPLE.test:443/')))
  assert.notEqual(partitionFor(origin), partitionFor('https://example.test:8443'))
  assert.equal(sameOrigin('https://example.test/api', origin), true)
  assert.equal(sameOrigin('https://example.test.evil.test', origin), false)
  assert.equal(sameOrigin('data:text/html,hi', origin), false)
})

test('external links cannot invoke local programs or carry embedded credentials', () => {
  for (const value of ['file:///tmp/a', 'javascript:alert(1)', 'ms-settings:', 'https://u:p@example.test', 'bad']) assert.equal(externalURL(value), null)
  assert.equal(externalURL('https://example.test/help'), 'https://example.test/help')
  assert.equal(externalURL('mailto:support@example.test'), 'mailto:support@example.test')
})

test('the selected server survives restart; malformed settings recover to selection', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'galaris-desktop-'))
  try {
    assert.equal(await readServer(directory, false), '')
    await writeServer(directory, 'https://example.test')
    assert.equal(await readServer(directory, false), 'https://example.test')
    assert.deepEqual(JSON.parse(await readFile(path.join(directory, 'server.json'), 'utf8')), { server: 'https://example.test' })
    await writeFile(path.join(directory, 'server.json'), '{broken')
    assert.equal(await readServer(directory, false), '')
    await writeServer(directory, 'http://127.0.0.1:8000')
    assert.equal(await readServer(directory, false), '')
    assert.equal(await readServer(directory, true), 'http://127.0.0.1:8000')
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('desktop catalogs preserve keys and interpolation parameters in every language', () => {
  const keys = Object.keys(messages.en).sort()
  for (const catalog of [messages.fr, messages.zh]) {
    assert.deepEqual(Object.keys(catalog).sort(), keys)
    for (const key of keys as (keyof typeof messages.en)[]) {
      assert.deepEqual(catalog[key].match(/\{\w+\}/g)?.sort(), messages.en[key].match(/\{\w+\}/g)?.sort(), key)
    }
  }
})

test('shell presentation accepts finite geometry and plain colors only', () => {
  const layout = { integrated: true, fullscreen: true, left: 260, dark: false, surface: 'rgb(250, 250, 250)', ratio: 1 }
  assert.deepEqual(readShellLayout(shellMessage + JSON.stringify({ ...layout, command: 'quit' })), layout)
  for (const message of ['unrelated', shellMessage + '{', shellMessage + 'null',
    shellMessage + JSON.stringify({ ...layout, left: -1 }),
    shellMessage + JSON.stringify({ ...layout, surface: 'url(https://example.test/)' }),
    shellMessage + JSON.stringify({ ...layout, integrated: 'true' }),
    shellMessage + JSON.stringify({ ...layout, fullscreen: 'true' }),
    shellMessage + JSON.stringify(layout).replace('260', '1e999')]) assert.equal(readShellLayout(message), undefined)
})
