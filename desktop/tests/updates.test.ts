import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { configureUpdates } from '../src/updates.ts'
import type { DesktopState } from '../src/contracts.ts'

class SyntheticUpdater extends EventEmitter {
  autoDownload = false
  autoInstallOnAppQuit = true
  allowPrerelease = true
  allowDowngrade = true
  disableWebInstaller = false
  checks = 0
  installs = 0
  fail = false
  async checkForUpdates() {
    this.checks++
    this.emit('checking-for-update')
    if (this.fail) throw new Error('synthetic network failure')
    this.emit('update-not-available')
  }
  quitAndInstall() { this.installs++ }
}

test('concurrent checks share one request; a failed request can be retried', async () => {
  const updater = new SyntheticUpdater()
  const states: DesktopState['update'][] = []
  const control = configureUpdates(updater, 'idle', value => states.push(value), () => {})
  updater.fail = true
  await Promise.all([control.check(), control.check(), control.check()])
  assert.equal(updater.checks, 1)
  assert.equal(states.at(-1)?.status, 'error')
  updater.fail = false
  await control.check()
  assert.equal(updater.checks, 2)
  assert.equal(states.at(-1)?.status, 'current')
})

test('download completion requires explicit installation and survives late events', async () => {
  const updater = new SyntheticUpdater()
  let ready = 0
  let state: DesktopState['update'] | undefined
  const control = configureUpdates(updater, 'idle', value => { state = value }, () => { ready++ })
  control.install()
  assert.equal(updater.installs, 0)
  updater.emit('update-available', { version: '0.4.0' })
  updater.emit('download-progress', { percent: 50 })
  assert.equal(state?.percent, 50)
  await control.check()
  assert.equal(updater.checks, 0)
  updater.emit('update-downloaded', { version: '0.4.0' })
  updater.emit('update-downloaded', { version: '0.4.0' })
  updater.emit('update-not-available')
  updater.emit('error', new Error('late error'))
  assert.equal(state?.status, 'ready')
  assert.equal(ready, 1)
  assert.equal(updater.installs, 0)
  assert.equal(updater.autoInstallOnAppQuit, false)
  assert.equal(updater.allowPrerelease, false)
  assert.equal(updater.allowDowngrade, false)
  assert.equal(updater.disableWebInstaller, true)
  control.install()
  assert.equal(updater.installs, 1)
})

test('development and unmanaged packages do not check or install automatically', async () => {
  for (const status of ['disabled', 'manual'] as const) {
    const updater = new SyntheticUpdater()
    const control = configureUpdates(updater, status, () => {}, () => {})
    await control.check()
    updater.emit('update-downloaded', { version: '0.4.0' })
    control.install()
    assert.equal(updater.checks, 0)
    assert.equal(updater.installs, 0)
  }
})
