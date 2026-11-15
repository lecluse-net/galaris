import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test'
import { createServer, type Server } from 'node:http'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'

let server: Server
let origin: string
let profile: string
let client: ElectronApplication | undefined
let pageErrors: string[] = []

test.beforeAll(async () => {
  server = createServer((request, response) => {
    if (request.url === '/download') {
      response.writeHead(200, { 'Content-Type': 'text/plain', 'Content-Disposition': 'attachment; filename="synthetic.txt"' })
      response.end('Synthetic desktop export')
      return
    }
    response.writeHead(200, { 'Content-Type': 'text/html' })
    response.end(`<!doctype html><title>Synthetic Galaris</title><h1>Synthetic Galaris server</h1>
      <button onclick="localStorage.setItem('draft','Synthetic draft'); document.cookie='session=synthetic; max-age=3600; path=/'; document.querySelector('p').textContent='Saved'">Save draft</button>
      <button onclick="navigator.clipboard.writeText('Synthetic clipboard').then(()=>document.querySelector('p').textContent='Copied').catch(error=>document.querySelector('p').textContent=error.name)">Copy text</button>
      <button onclick="navigator.mediaDevices.getUserMedia({audio:true}).then(stream=>{stream.getTracks().forEach(track=>track.stop());document.querySelector('p').textContent='Microphone ready'}).catch(error=>document.querySelector('p').textContent=error.name)">Test microphone</button>
      <p></p><a href='/download'>Download</a><a href='https://example.test/help' target='_blank'>External link</a>
      <button onclick="const tab=window.open('about:blank'); tab.opener=null; tab.location.replace(window.URL.createObjectURL(new Blob(['<h1>Synthetic preview</h1>'],{type:'text/html'})))">Preview</button>`)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Missing synthetic HTTP endpoint')
  origin = `http://127.0.0.1:${address.port}`
})
test.afterAll(async () => { await new Promise<void>(resolve => server.close(() => resolve())) })
test.beforeEach(async () => { profile = await mkdtemp(path.join(tmpdir(), 'galaris-desktop-browser-')); pageErrors = [] })
test.afterEach(async ({}, info) => {
  if (client && info.status !== info.expectedStatus) {
    for (const [index, page] of (await client.windows()).entries()) {
      console.log('Desktop failure URL:', page.url())
      await page.screenshot({ path: path.join('..', 'artifacts', 'desktop', `failure-${info.testId}-${index}.png`), timeout: 2000 }).catch(() => {})
      console.log(await page.locator('body').innerText().catch(() => 'No renderer body'))
    }
  }
  for (const page of client?.windows() ?? []) await page.evaluate(() => { window.onbeforeunload = null }).catch(() => {})
  await client?.close(); client = undefined
  await rm(profile, { recursive: true, force: true })
  expect(pageErrors).toEqual([])
})

async function launch(expectVisible = true): Promise<Page> {
  client = await electron.launch({
    args: ['--no-sandbox', '--lang=en-US', '--use-fake-device-for-media-stream', '.'],
    env: { ...process.env, LANG: 'en_US.UTF-8', GALARIS_DESKTOP_USER_DATA: profile }
  })
  const launcher = await client.firstWindow()
  for (const page of client.windows()) page.on('pageerror', error => pageErrors.push(error.message))
  client.on('window', page => page.on('pageerror', error => pageErrors.push(error.message)))
  if (expectVisible) await expect(launcher.getByRole('heading', { name: 'Galaris desktop' })).toBeVisible()
  return launcher
}
async function openServer(launcher: Page, address = origin): Promise<Page> {
  if (!client) throw new Error('Client not running')
  await launcher.getByRole('textbox', { name: 'Server address' }).fill(address)
  const window = client.waitForEvent('window', page => !page.url().startsWith('galaris-desktop:'))
  await launcher.getByRole('button', { name: 'Connect', exact: true }).click()
  const remote = await window
  await expect(remote.getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
  await expect.poll(() => client!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(win => win.webContents.getURL().startsWith('galaris-desktop:'))?.isVisible())).toBe(false)
  return remote
}

test('connects, retains cookies and drafts after restart, and isolates servers', async () => {
  const launcher = await launch()
  const remote = await openServer(launcher)
  await remote.getByRole('button', { name: 'Save draft' }).click()
  await expect(remote.getByText('Saved')).toBeVisible()
  expect(await remote.evaluate(() => ({ desktop: typeof window.galarisDesktop, node: typeof (window as unknown as { require?: unknown }).require }))).toEqual({ desktop: 'undefined', node: 'undefined' })
  await client!.close(); client = undefined
  const reopened = await launch(false)
  // Startup restores the selected server automatically.
  await expect.poll(async () => (await client!.windows()).find(page => page.url().startsWith(origin))?.url()).toContain(origin)
  const restored = (await client!.windows()).find(page => page.url().startsWith(origin))!
  await expect(restored.getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
  expect(await restored.evaluate(() => localStorage.getItem('draft'))).toBe('Synthetic draft')
  expect(await restored.evaluate(() => document.cookie)).toContain('session=synthetic')
  await client!.evaluate(({ Menu }) => Menu.getApplicationMenu()!.items[0]!.submenu!.items[0]!.click())
  await expect(reopened.getByRole('textbox', { name: 'Server address' })).toBeVisible()
  // localhost is a separate origin even though it reaches the same synthetic server.
  const otherOrigin = origin.replace('127.0.0.1', 'localhost')
  const other = await openServer(reopened, otherOrigin)
  expect(await other.evaluate(() => localStorage.getItem('draft'))).toBeNull()
  expect(await other.evaluate(() => document.cookie)).not.toContain('session=synthetic')
})

test('invalid addresses and connection failures remain recoverable without replacing the saved server', async () => {
  const launcher = await launch()
  await launcher.getByRole('textbox', { name: 'Server address' }).fill('http://example.test')
  await launcher.getByRole('button', { name: 'Connect', exact: true }).click()
  await expect(launcher.getByRole('alert')).toContainText('HTTPS')
  await launcher.getByRole('textbox', { name: 'Server address' }).fill('http://127.0.0.1:1')
  await launcher.getByRole('button', { name: 'Connect', exact: true }).click()
  await expect(launcher.getByRole('alert')).toContainText('Cannot reach this server')
  await openServer(launcher)
  expect(JSON.parse(await readFile(path.join(profile, 'server.json'), 'utf8')).server).toBe(origin)
})

test('downloads and standalone previews work; external links never launch custom programs', async () => {
  const remote = await openServer(await launch())
  const destination = path.join(profile, 'download.txt')
  await client!.evaluate(({ BrowserWindow }, output) => {
    for (const win of BrowserWindow.getAllWindows()) {
      if (win.webContents.getURL().startsWith('http:')) win.webContents.session.once('will-download', (_event: unknown, item: Electron.DownloadItem) => item.setSavePath(output))
    }
  }, destination)
  await remote.getByRole('link', { name: 'Download', exact: true }).click()
  await expect.poll(async () => { try { return await readFile(destination, 'utf8') } catch { return '' } }).toBe('Synthetic desktop export')
  const previewEvent = client!.waitForEvent('window')
  await remote.getByRole('button', { name: 'Preview' }).click()
  const preview = await previewEvent
  await expect(preview.getByRole('heading', { name: 'Synthetic preview' })).toBeVisible()
  expect(await preview.evaluate(() => typeof window.galarisDesktop)).toBe('undefined')
  await client!.evaluate(({ shell }) => {
    const opened: string[] = []
    ;(globalThis as unknown as { opened: string[] }).opened = opened
    shell.openExternal = async (url: string) => { opened.push(url) }
  })
  await remote.getByRole('link', { name: 'External link' }).click()
  expect(await client!.evaluate(() => (globalThis as unknown as { opened: string[] }).opened)).toEqual(['https://example.test/help'])
  await remote.evaluate(() => window.open('file:///tmp/synthetic.txt'))
  expect(await client!.evaluate(() => (globalThis as unknown as { opened: string[] }).opened)).toHaveLength(1)
})

test('OAuth-style HTTPS navigation retains tab state and can return to Galaris', async () => {
  const remote = await openServer(await launch())
  await client!.context().route('https://identity.example.test/**', route => route.fulfill({ contentType: 'text/html', body: `<h1>Synthetic identity provider</h1><a href="${origin}/connection/oauth-callback">Return to Galaris</a>` }))
  await remote.evaluate(() => { sessionStorage.setItem('oauth-state', 'synthetic'); location.assign('https://identity.example.test/authorize') })
  await expect(remote.getByRole('heading', { name: 'Synthetic identity provider' })).toBeVisible()
  await remote.getByRole('link', { name: 'Return to Galaris' }).click()
  await expect(remote.getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
  expect(await remote.evaluate(() => sessionStorage.getItem('oauth-state'))).toBe('synthetic')
})

test('clipboard writing and microphone permission work through the desktop boundary', async () => {
  const remote = await openServer(await launch())
  await client!.evaluate(({ dialog }) => {
    const tracker = { prompts: 0 }
    ;(globalThis as unknown as { permissionsTest: typeof tracker }).permissionsTest = tracker
    dialog.showMessageBox = (async () => { tracker.prompts++; return { response: 1, checkboxChecked: false } }) as typeof dialog.showMessageBox
  })
  await remote.getByRole('button', { name: 'Copy text', exact: true }).click()
  await expect(remote.getByText('Copied', { exact: true })).toBeVisible()
  await remote.getByRole('button', { name: 'Test microphone', exact: true }).click()
  await expect(remote.getByText('Microphone ready', { exact: true })).toBeVisible()
  expect(await client!.evaluate(() => (globalThis as unknown as { permissionsTest: { prompts: number } }).permissionsTest.prompts)).toBe(1)
})

test('cancelled late connections preserve the working server and allow retry', async () => {
  const launcher = await launch()
  await openServer(launcher)
  await client!.evaluate(({ Menu }) => Menu.getApplicationMenu()!.items[0]!.submenu!.items[0]!.click())
  const stalled = createServer((_request, response) => { response.on('close', () => {} /* synthetic stalled response */) })
  await new Promise<void>(resolve => stalled.listen(0, '127.0.0.1', resolve))
  try {
    const address = stalled.address()
    if (!address || typeof address === 'string') throw new Error('Missing stalled endpoint')
    await launcher.getByRole('textbox', { name: 'Server address' }).fill(`http://127.0.0.1:${address.port}`)
    await launcher.getByRole('button', { name: 'Connect', exact: true }).click()
    await launcher.getByRole('button', { name: 'Cancel', exact: true }).click()
    expect(JSON.parse(await readFile(path.join(profile, 'server.json'), 'utf8')).server).toBe(origin)
    await openServer(launcher)
  } finally {
    stalled.closeAllConnections()
    await new Promise<void>(resolve => stalled.close(() => resolve()))
  }
})

test('launcher supports the keyboard and renders in light, dark and narrow windows', async () => {
  const launcher = await launch()
  for (const colorScheme of ['light', 'dark'] as const) {
    await launcher.emulateMedia({ colorScheme })
    await launcher.screenshot({ path: `../artifacts/desktop/launcher-${colorScheme}.png` })
  }
  await client!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setSize(480, 720))
  await launcher.screenshot({ path: '../artifacts/desktop/launcher-narrow.png' })
  await launcher.getByRole('textbox', { name: 'Server address' }).fill(origin)
  const remote = client!.waitForEvent('window')
  await launcher.getByRole('textbox', { name: 'Server address' }).press('Enter')
  await expect((await remote).getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
})

test('unsaved edits can prevent quitting and switching servers without losing the current session', async () => {
  const launcher = await launch()
  const remote = await openServer(launcher)
  await remote.getByRole('button', { name: 'Save draft' }).click()
  await remote.evaluate(() => { window.onbeforeunload = event => { event.preventDefault(); event.returnValue = ''; return '' } })
  await client!.evaluate(({ app }) => app.quit())
  await expect(launcher.getByRole('alert')).toContainText('unsaved changes')
  expect(remote.isClosed()).toBe(false)
  await launcher.getByRole('textbox', { name: 'Server address' }).fill(origin.replace('127.0.0.1', 'localhost'))
  const pendingWindow = client!.waitForEvent('window')
  await launcher.getByRole('button', { name: 'Connect', exact: true }).click()
  const pending = await pendingWindow
  await expect.poll(() => pending.isClosed()).toBe(true)
  await expect(launcher.getByRole('alert')).toContainText('unsaved changes')
  expect(remote.isClosed()).toBe(false)
  expect(JSON.parse(await readFile(path.join(profile, 'server.json'), 'utf8')).server).toBe(origin)
  await remote.evaluate(() => { window.onbeforeunload = null })
})

test('the real updater rejects corrupted bytes and downloads a verified retry without installing', async () => {
  await launch()
  let corrupted = true
  const bytes = Buffer.from('Entirely synthetic update payload; never an executable.')
  const digest = createHash('sha512').update(bytes).digest('base64')
  const feed = createServer((request, response) => {
    if (request.url?.split('?')[0]?.endsWith('.yml')) {
      const extension = request.url.includes('linux') ? 'AppImage' : 'exe'
      response.writeHead(200, { 'Content-Type': 'text/yaml' })
      response.end(`version: 99.0.0\nfiles:\n  - url: Synthetic.${extension}\n    sha512: ${digest}\n    size: ${bytes.length}\npath: Synthetic.${extension}\nsha512: ${digest}\nreleaseDate: '2026-01-01T00:00:00.000Z'\n`)
    } else {
      response.writeHead(200, { 'Content-Type': 'application/octet-stream' })
      response.end(corrupted ? Buffer.from('Corrupted synthetic payload') : bytes)
    }
  })
  await new Promise<void>(resolve => feed.listen(0, '127.0.0.1', resolve))
  try {
    const address = feed.address()
    if (!address || typeof address === 'string') throw new Error('Missing update feed')
    const setup = { url: `http://127.0.0.1:${address.port}`, profile }
    await client!.evaluate(async ({}, options) => {
      const { createRequire } = process.getBuiltinModule('module')
      const require = createRequire(`${process.cwd()}/package.json`)
      const { AppImageUpdater, NsisUpdater } = require('electron-updater') as typeof import('electron-updater')
      const { writeFile } = process.getBuiltinModule('fs/promises')
      const instance = process.platform === 'linux' ? new AppImageUpdater() : new NsisUpdater()
      const config = `${options.profile}/synthetic-update.yml`
      await writeFile(config, 'updaterCacheDirName: galaris-synthetic-update\n')
      if (process.platform === 'linux') {
        process.env.APPIMAGE = `${options.profile}/Synthetic-old.AppImage`
        await writeFile(process.env.APPIMAGE, 'Synthetic previous version')
      }
      instance.updateConfigPath = config
      instance.forceDevUpdateConfig = true
      instance.autoInstallOnAppQuit = false
      instance.disableDifferentialDownload = true
      instance.logger = null
      instance.setFeedURL({ provider: 'generic', url: options.url })
      const tracker = { instance, ready: 0, errors: [] as string[] }
      instance.on('update-downloaded', () => { tracker.ready++ })
      instance.on('error', error => tracker.errors.push(error.message))
      ;(globalThis as unknown as { updaterTest: typeof tracker }).updaterTest = tracker
    }, setup)
    const attempt = async () => client!.evaluate(async () => {
      const tracker = (globalThis as unknown as { updaterTest: { instance: import('electron-updater').AppUpdater; ready: number; errors: string[] } }).updaterTest
      try {
        const result = await tracker.instance.checkForUpdates()
        const files = await result?.downloadPromise
        return { ready: tracker.ready, errors: tracker.errors, files: files ?? [] }
      } catch { return { ready: tracker.ready, errors: tracker.errors, files: [] as string[] } }
    })
    const failed = await attempt()
    expect(failed.ready).toBe(0)
    expect(failed.errors.join(' ')).toMatch(/sha512|checksum/i)
    corrupted = false
    const success = await attempt()
    expect(success.ready).toBe(1)
    expect(success.files).toHaveLength(1)
    const contents = await client!.evaluate(async ({}, filename) => process.getBuiltinModule('fs/promises').readFile(filename, 'utf8'), success.files[0]!)
    expect(contents).toBe(bytes.toString())
    expect(await client!.evaluate(() => (globalThis as unknown as { updaterTest: { instance: { autoInstallOnAppQuit: boolean } } }).updaterTest.instance.autoInstallOnAppQuit)).toBe(false)
  } finally {
    feed.closeAllConnections()
    await new Promise<void>(resolve => feed.close(() => resolve()))
  }
})
