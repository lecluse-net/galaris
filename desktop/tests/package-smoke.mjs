import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { _electron as electron } from '@playwright/test'

// Exercise the actual packaged ASAR and preload, rather than source entrypoints.
const profile = await mkdtemp(path.join(tmpdir(), 'galaris-packaged-'))
let client
try {
  client = await electron.launch({
    executablePath: path.resolve('release/linux-unpacked/galaris-desktop'),
    args: ['--no-sandbox', '--lang=en-US', `--user-data-dir=${profile}`],
    env: { ...process.env, LANG: 'en_US.UTF-8', XDG_CONFIG_HOME: profile }
  })
  const launcher = await client.firstWindow()
  await launcher.getByRole('heading', { name: 'Galaris desktop' }).waitFor()
  assert.equal(await client.evaluate(({ app }) => app.isPackaged), true)
  await launcher.getByRole('textbox', { name: 'Server address' }).fill('http://127.0.0.1:8000')
  await launcher.getByRole('button', { name: 'Connect', exact: true }).click()
  await launcher.getByRole('alert').filter({ hasText: 'HTTPS' }).waitFor()
  await client.context().route('https://packaged.example.test/**', route => route.fulfill({
    contentType: 'text/html', body: '<h1>Synthetic packaged server</h1>'
  }))
  await launcher.getByRole('textbox', { name: 'Server address' }).fill('https://packaged.example.test')
  const remoteWindow = client.waitForEvent('window', page => page.url().startsWith('http'))
  await launcher.getByRole('button', { name: 'Connect', exact: true }).click()
  const remote = await remoteWindow
  await remote.getByRole('heading', { name: 'Synthetic packaged server' }).waitFor()
  assert.equal(await remote.evaluate(() => typeof window.galarisDesktop), 'undefined')
  console.log('Packaged Linux client: launcher, ASAR/preload, HTTPS enforcement and remote isolation passed.')
} finally {
  await client?.close()
  await rm(profile, { recursive: true, force: true })
}
