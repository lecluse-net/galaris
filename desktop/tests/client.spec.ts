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
    if (request.url === '/shell') {
      response.writeHead(200, { 'Content-Type': 'text/html' })
      response.end(`<!doctype html><title>Synthetic workspace</title><style>
        *{box-sizing:border-box}body{margin:0;font:16px Arial;background:white;color:#292c30}
        aside{position:fixed;top:0;bottom:0;left:0;width:260px;background:#f5f5f5;padding:16px}
        .page-container{padding-left:260px}.q-page{padding:20px;min-height:100vh}h1{margin:0 0 20px}
        .q-dialog:not([hidden]){position:fixed;inset:0;display:grid;place-items:center;z-index:6000}
        .q-dialog__backdrop{position:absolute;inset:0;background:rgba(0,0,0,.4)}
        .q-dialog section{position:relative;padding:20px;background:white;color:#292c30}
        .q-dialog__inner--maximized,.fullscreen-preview{position:fixed;inset:0;background:white;z-index:6000}
        .q-dialog__inner--maximized{z-index:6001}
        .fullscreen-preview{background:#202020;color:white;z-index:7000}
        .body--dark{background:#101010;color:#eee}.body--dark aside{background:#272727}
      </style><aside><strong>Synthetic navigation</strong><p><button onclick="document.querySelector('.page-container').style.paddingLeft='80px';document.querySelector('aside').style.width='80px'">Collapse menu</button></p></aside>
      <main class="page-container"><section class="q-page"><h1>Synthetic workspace</h1><label>Workspace draft<input></label>
      <button onclick="document.body.classList.toggle('body--dark')">Toggle theme</button>
      <button onclick="document.querySelector('.q-dialog').hidden=false">Open centered dialog</button>
      <button onclick="document.querySelector('.fullscreen-preview').hidden=false">Open full screen preview</button>
      <a href="/second">Leave shell</a></section></main>
      <div hidden class="q-dialog" role="dialog" aria-modal="true" aria-label="Synthetic centered dialog">
        <div class="q-dialog__backdrop" onclick="this.parentElement.hidden=true"></div>
        <section><button onclick="document.querySelector('.q-dialog__inner--maximized').hidden=false">Open nested dialog</button></section>
      </div>
      <div hidden class="q-dialog__inner--maximized" role="dialog" aria-label="Synthetic full screen dialog">
        <button onclick="this.parentElement.hidden=true">Close full screen dialog</button>
        <button onclick="document.querySelector('.fullscreen-preview').hidden=false">Preview from dialog</button>
      </div>
      <div hidden class="fullscreen-preview" role="dialog" aria-label="Synthetic full screen preview">
        <button onclick="this.parentElement.hidden=true">Close full screen preview</button>
      </div>`)
      return
    }
    if (request.url === '/download') {
      response.writeHead(200, { 'Content-Type': 'text/plain', 'Content-Disposition': 'attachment; filename="synthetic.txt"' })
      response.end('Synthetic desktop export')
      return
    }
    response.writeHead(200, { 'Content-Type': 'text/html' })
    response.end(`<!doctype html><title>${request.url === '/second' ? 'Synthetic second page' : 'Synthetic Galaris'}</title><h1>Synthetic Galaris server</h1>
      <button onclick="localStorage.setItem('draft','Synthetic draft'); document.cookie='session=synthetic; max-age=3600; path=/'; document.querySelector('p').textContent='Saved'">Save draft</button>
      <button onclick="navigator.clipboard.writeText('Synthetic clipboard').then(()=>document.querySelector('p').textContent='Copied').catch(error=>document.querySelector('p').textContent=error.name)">Copy text</button>
      <button onclick="navigator.mediaDevices.getUserMedia({audio:true}).then(stream=>{stream.getTracks().forEach(track=>track.stop());document.querySelector('p').textContent='Microphone ready'}).catch(error=>document.querySelector('p').textContent=error.name)">Test microphone</button>
      <label>Draft<textarea spellcheck="true"></textarea></label>
      <p></p><a href='/download'>Download</a><a href='/second' target='_blank' rel='noopener noreferrer'>Internal link</a><a href='https://example.test/help' target='_blank'>External link</a>
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
  const window = client.waitForEvent('window', page => page.url().startsWith('http'))
  await launcher.getByRole('button', { name: 'Connect', exact: true }).click()
  const remote = await window
  await expect(remote.getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
  await expect.poll(() => client!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'galaris-desktop://launcher/index.html')?.isVisible())).toBe(false)
  return remote
}

async function shortcut(keyCode: string, modifiers: ('control' | 'shift')[] = ['control']): Promise<void> {
  // CDP keyboard events bypass Electron's native accelerators and before-input-event.
  await client!.evaluate(({ webContents }, input) => {
    const contents = webContents.getFocusedWebContents()!
    contents.sendInputEvent({ type: 'keyDown', ...input })
    contents.sendInputEvent({ type: 'keyUp', ...input })
  }, { keyCode, modifiers })
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
  await client!.evaluate(({ webContents }, output) => {
    for (const contents of webContents.getAllWebContents()) {
      if (contents.getURL().startsWith('http:')) contents.session.once('will-download', (_event: unknown, item: Electron.DownloadItem) => item.setSavePath(output))
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
  const remote = client!.waitForEvent('window', page => page.url().startsWith('http'))
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

test('an automatic page reload preserves dirty work without opening server selection or blocking quit', async () => {
  const launcher = await launch()
  const remote = await openServer(launcher)
  const draft = remote.getByRole('textbox', { name: 'Draft' })
  await draft.click()
  await draft.fill('Work in progress during an update')
  await remote.evaluate(() => {
    window.onbeforeunload = event => { event.preventDefault(); event.returnValue = '' }
  })
  // Playwright accepts beforeunload dialogs automatically unless the test handles them.
  remote.once('dialog', dialog => { void dialog.dismiss().catch(() => {}) })
  await client!.evaluate(async ({ webContents }) => {
    const contents = webContents.getAllWebContents().find(page => page.getURL().startsWith('http:'))!
    await new Promise<void>(resolve => {
      contents.once('will-prevent-unload', () => resolve())
      // This matches the renderer-initiated reload on a PWA controller change.
      void contents.executeJavaScript('window.location.reload()').catch(() => {})
    })
  })
  const launcherWindow = await client!.browserWindow(launcher)
  expect(await launcherWindow.evaluate(window => window.isVisible())).toBe(false)
  await expect(draft).toHaveValue('Work in progress during an update')
  await draft.fill('Still editing')
  await remote.evaluate(() => { window.onbeforeunload = null })
  const exited = client!.waitForEvent('close')
  await client!.evaluate(({ BrowserWindow }) => {
    BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'about:blank#galaris-workspace')!.close()
  })
  await exited
  client = undefined
})

test('an update restart refused by an editor returns to the current workspace', async () => {
  const launcher = await launch()
  const remote = await openServer(launcher)
  const draft = remote.getByRole('textbox', { name: 'Draft' })
  await draft.click()
  await draft.fill('Preserve this draft before updating')
  await remote.evaluate(() => {
    window.onbeforeunload = event => { event.preventDefault(); event.returnValue = '' }
  })
  remote.once('dialog', dialog => { void dialog.dismiss().catch(() => {}) })
  await client!.evaluate(({ dialog }) => {
    const require = process.getBuiltinModule('module').createRequire(`${process.cwd()}/package.json`)
    const { autoUpdater } = require('electron-updater') as typeof import('electron-updater')
    const prompts: { owner: string; message: string }[] = []
    ;(globalThis as unknown as { updatePrompts: typeof prompts }).updatePrompts = prompts
    // Simulate a completed download and the native confirmation.
    dialog.showMessageBox = (async (owner: Electron.BrowserWindow, options: Electron.MessageBoxOptions) => {
      prompts.push({ owner: owner.webContents.getURL(), message: options.message })
      return { response: options.type === 'info' ? 1 : 0, checkboxChecked: false }
    }) as typeof dialog.showMessageBox
    autoUpdater.emit('update-downloaded', {
      version: '99.0.0', files: [], downloadedFile: 'synthetic-update', path: 'synthetic-update',
      sha512: '', releaseDate: '2026-01-01T00:00:00.000Z'
    })
  })
  await expect.poll(() => client!.evaluate(() => (
    globalThis as unknown as { updatePrompts: { owner: string; message: string }[] }
  ).updatePrompts)).toEqual([
    { owner: 'about:blank#galaris-workspace', message: expect.stringContaining('update is ready') },
    { owner: 'about:blank#galaris-workspace', message: expect.stringContaining('unsaved changes') }
  ])
  const launcherWindow = await client!.browserWindow(launcher)
  expect(await launcherWindow.evaluate(window => window.isVisible())).toBe(false)
  await expect(draft).toHaveValue('Preserve this draft before updating')
  await draft.fill('Continue editing')
  await remote.evaluate(() => { window.onbeforeunload = null })
  const exited = client!.waitForEvent('close')
  await client!.evaluate(({ app }) => app.quit())
  await exited
  client = undefined
})

test('browser tabs preserve drafts, share the server session and protect unsaved edits', async () => {
  const launcher = await launch()
  const first = await openServer(launcher)
  const chrome = client!.windows().find(page => page.url().endsWith('?tabs'))!
  await first.getByRole('textbox', { name: 'Draft' }).fill('Unsent synthetic draft')
  await first.getByRole('button', { name: 'Save draft' }).click()
  const created = client!.waitForEvent('window', page => page.url().startsWith('http'))
  await chrome.getByRole('button', { name: 'New tab', exact: true }).click()
  const second = await created
  await expect(second.getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
  await expect(chrome.getByRole('tab')).toHaveCount(2)
  expect(await second.evaluate(() => document.cookie)).toContain('session=synthetic')
  expect(await second.evaluate(() => typeof window.galarisDesktop)).toBe('undefined')
  await second.getByRole('textbox', { name: 'Draft' }).fill('Second synthetic draft')
  await shortcut('Tab', ['control', 'shift'])
  await expect(chrome.getByRole('tab').first()).toHaveAttribute('aria-selected', 'true')
  await expect(first.getByRole('textbox', { name: 'Draft' })).toHaveValue('Unsent synthetic draft')
  const linked = client!.waitForEvent('window', page => page.url().startsWith('http'))
  await first.getByRole('link', { name: 'Internal link' }).click()
  const third = await linked
  await expect(third).toHaveURL(`${origin}/second`)
  await expect(chrome.getByRole('tab')).toHaveCount(3)
  await expect(chrome.getByRole('tab', { name: 'Synthetic second page', exact: true })).toBeVisible()
  await second.evaluate(() => { document.title = 'Synthetic Tasks' })
  await expect(chrome.getByRole('tab', { name: 'Synthetic Tasks', exact: true })).toBeVisible()
  await expect(chrome.getByRole('tab', { name: 'Synthetic Galaris', exact: true })).toHaveCount(1)
  await shortcut('W')
  await expect.poll(() => third.isClosed()).toBe(true)
  await expect(chrome.getByRole('tab')).toHaveCount(2)
  await expect(second.getByRole('textbox', { name: 'Draft' })).toHaveValue('Second synthetic draft')
  const keyboardTab = client!.waitForEvent('window', page => page.url().startsWith('http'))
  await shortcut('T')
  const fourth = await keyboardTab
  await expect(fourth.getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
  await shortcut('W')
  await expect.poll(() => fourth.isClosed()).toBe(true)
  for (const colorScheme of ['light', 'dark'] as const) {
    await chrome.emulateMedia({ colorScheme })
    await chrome.screenshot({ path: `../artifacts/desktop/tabs-${colorScheme}.png` })
  }
  await client!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'about:blank#galaris-workspace')!.setSize(480, 720))
  await chrome.screenshot({ path: '../artifacts/desktop/tabs-narrow.png' })
  // A dirty background tab must also veto closing the whole application.
  await first.evaluate(() => { window.onbeforeunload = event => { event.preventDefault(); event.returnValue = ''; return '' } })
  await chrome.getByRole('button', { name: 'Close tab: Synthetic Galaris' }).first().click()
  await expect(launcher.getByRole('alert')).toContainText('unsaved changes')
  expect(first.isClosed()).toBe(false)
  await chrome.getByRole('tab').last().click()
  await client!.evaluate(({ app }) => app.quit())
  await expect(launcher.getByRole('alert')).toContainText('unsaved changes')
  expect(first.isClosed()).toBe(false)
  await first.evaluate(() => { window.onbeforeunload = null })
  const finalClose = chrome.waitForEvent('close')
  await chrome.getByRole('button', { name: 'Close tab: Synthetic Galaris' }).click()
  await finalClose
  expect(first.isClosed()).toBe(true)
})

test('navigation controls follow the active tab and the menu remains accessible with its bar hidden', async () => {
  const launcher = await launch()
  const first = await openServer(launcher)
  const chrome = client!.windows().find(page => page.url().endsWith('?tabs'))!
  const back = chrome.getByRole('button', { name: 'Back', exact: true })
  const forward = chrome.getByRole('button', { name: 'Forward', exact: true })
  await expect(back).toBeDisabled()
  await expect(forward).toBeDisabled()

  // Full-page navigation and SPA history must both refresh the controls.
  await first.getByRole('link', { name: 'Internal link' }).evaluate(link => link.removeAttribute('target'))
  await first.getByRole('link', { name: 'Internal link' }).click()
  await expect(first).toHaveURL(`${origin}/second`)
  await expect(back).toBeEnabled()
  await back.click()
  await expect(first).toHaveURL(`${origin}/`)
  await expect(back).toBeDisabled()
  await expect(forward).toBeEnabled()
  await forward.click()
  await expect(first).toHaveURL(`${origin}/second`)
  await expect(forward).toBeDisabled()
  await first.evaluate(() => history.pushState({}, '', '/spa'))
  await back.click()
  await expect(first).toHaveURL(`${origin}/second`)
  await expect(forward).toBeEnabled()
  await first.evaluate(() => history.pushState({}, '', '/replacement'))
  await expect(forward).toBeDisabled()

  const created = client!.waitForEvent('window', page => page.url().startsWith('http'))
  await chrome.getByRole('button', { name: 'New tab', exact: true }).click()
  const second = await created
  await expect(second.getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
  await expect(back).toBeDisabled()
  await expect(forward).toBeDisabled()
  await chrome.getByRole('tab').first().click()
  await expect(back).toBeEnabled()
  await back.click()
  await expect(first).toHaveURL(`${origin}/second`)
  await expect(second).toHaveURL(`${origin}/`)

  const firstDraft = first.getByRole('textbox', { name: 'Draft' })
  const secondDraft = second.getByRole('textbox', { name: 'Draft' })
  await firstDraft.fill('Reset by reload')
  await secondDraft.fill('Preserved in the background')
  await chrome.getByRole('button', { name: 'Reload', exact: true }).press('Enter')
  await expect(firstDraft).toHaveValue('')
  await expect(secondDraft).toHaveValue('Preserved in the background')
  await expect(first).toHaveURL(`${origin}/second`)
  await expect(back).toBeEnabled()
  await chrome.getByRole('tab', { name: 'Synthetic second page', exact: true }).click()
  await firstDraft.fill('Reset by keyboard shortcut')
  await shortcut('R')
  await expect(firstDraft).toHaveValue('')

  await chrome.getByRole('button', { name: 'Close tab: Synthetic second page', exact: true }).click()
  await expect(back).toBeDisabled()
  await expect(forward).toBeDisabled()

  expect(await client!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'about:blank#galaris-workspace')!.isMenuBarVisible())).toBe(false)
  await client!.evaluate(({ Menu }) => {
    const tracker = { shown: 0 }
    ;(globalThis as unknown as { menuTest: typeof tracker }).menuTest = tracker
    Menu.getApplicationMenu()!.on('menu-will-show', () => { tracker.shown++ })
  })
  await chrome.getByRole('button', { name: 'Open application menu', exact: true }).focus()
  await chrome.getByRole('button', { name: 'Open application menu', exact: true }).press('Enter')
  await expect.poll(() => client!.evaluate(() => (globalThis as unknown as { menuTest: { shown: number } }).menuTest.shown)).toBe(1)
  await client!.evaluate(({ Menu, BrowserWindow }) => {
    Menu.getApplicationMenu()!.closePopup(BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'about:blank#galaris-workspace')!)
    Menu.getApplicationMenu()!.items[0]!.submenu!.items[0]!.click()
  })
  await expect(launcher.getByRole('textbox', { name: 'Server address' })).toBeVisible()
})

test('integrated tabs keep navigation and content reachable through menu, theme, viewport and tab changes', async () => {
  const first = await openServer(await launch())
  await first.goto(`${origin}/shell`)
  const chrome = client!.windows().find(page => page.url().endsWith('?tabs'))!
  const bounds = async () => client!.evaluate(({ BrowserWindow, WebContentsView }) => {
    const owner = BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'about:blank#galaris-workspace')!
    const views = owner.contentView.children.filter((view): view is Electron.WebContentsView => view instanceof WebContentsView)
    const bar = views.find(view => view.webContents.getURL().endsWith('?tabs'))!
    return { chrome: { ...bar.getBounds(), visible: bar.getVisible() },
      page: views.find(view => view.webContents.getURL().endsWith('/shell'))!.getBounds() }
  })
  await expect(first.locator('html')).toHaveAttribute('data-galaris-desktop-shell', '')
  const padding = () => first.locator('.page-container').evaluate(element => parseFloat(getComputedStyle(element).paddingLeft))
  await expect.poll(async () => (await bounds()).chrome.x).toBe(await padding())
  expect((await bounds()).page.y).toBe(0)
  expect(await first.locator('h1').evaluate(element => element.getBoundingClientRect().top)).toBeGreaterThanOrEqual((await bounds()).chrome.height)
  await first.getByRole('textbox', { name: 'Workspace draft' }).fill('Preserved synthetic content')
  const openCentered = first.getByRole('button', { name: 'Open centered dialog' })
  const centered = first.getByRole('dialog', { name: 'Synthetic centered dialog' })
  async function dismissOverTabs(): Promise<void> {
    const { chrome: bar } = await bounds()
    await centered.locator('.q-dialog__backdrop').click({ position: { x: bar.x + 5, y: bar.height / 2 } })
    await expect(centered).toBeHidden()
    await expect.poll(async () => (await bounds()).chrome.visible).toBe(true)
  }
  await openCentered.click()
  await expect.poll(async () => (await bounds()).chrome.visible).toBe(false)
  await centered.getByRole('button', { name: 'Open nested dialog' }).click()
  await expect.poll(async () => (await bounds()).chrome.visible).toBe(false)
  const closeDialog = first.getByRole('button', { name: 'Close full screen dialog' })
  expect(await closeDialog.evaluate(element => element.getBoundingClientRect().top)).toBeLessThan((await bounds()).chrome.height)
  await first.getByRole('button', { name: 'Preview from dialog' }).click()
  await first.getByRole('button', { name: 'Close full screen preview' }).click()
  await expect.poll(async () => (await bounds()).chrome.visible).toBe(false)
  await closeDialog.click()
  await expect(centered).toBeVisible()
  await expect.poll(async () => (await bounds()).chrome.visible).toBe(false)
  await dismissOverTabs()
  await chrome.screenshot({ path: '../artifacts/desktop/integrated-tabs-light.png' })
  await first.getByRole('button', { name: 'Toggle theme' }).click()
  await expect(chrome.locator('body')).toHaveClass(/body--dark/)
  await chrome.screenshot({ path: '../artifacts/desktop/integrated-tabs-dark.png' })
  await first.getByRole('button', { name: 'Collapse menu' }).click()
  await expect.poll(async () => (await bounds()).chrome.x).toBe(await padding())
  const created = client!.waitForEvent('window', page => page.url().startsWith('http'))
  await chrome.getByRole('button', { name: 'New tab', exact: true }).click()
  const second = await created
  await expect(second.getByRole('heading', { name: 'Synthetic Galaris server' })).toBeVisible()
  await expect.poll(async () => (await bounds()).chrome.x).toBe(0)
  await chrome.getByRole('tab', { name: 'Synthetic workspace', exact: true }).click()
  await expect.poll(async () => (await bounds()).chrome.x).toBe(await padding())
  await expect(first.getByRole('textbox', { name: 'Workspace draft' })).toHaveValue('Preserved synthetic content')
  await client!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'about:blank#galaris-workspace')!.setSize(800, 720))
  await expect(first.locator('html')).not.toHaveAttribute('data-galaris-desktop-shell')
  await expect.poll(async () => (await bounds()).page.y).toBeGreaterThan(0)
  await expect.poll(async () => (await bounds()).chrome.x).toBe(0)
  await openCentered.click()
  await expect.poll(bounds).toMatchObject({ chrome: { visible: false }, page: { y: 0 } })
  await dismissOverTabs()
  await expect.poll(async () => (await bounds()).page.y).toBeGreaterThan(0)
  await first.getByRole('button', { name: 'Open full screen preview' }).click()
  await expect.poll(bounds).toMatchObject({ chrome: { visible: false }, page: { y: 0 } })
  await shortcut('Tab')
  await expect(chrome.getByRole('tab', { name: 'Synthetic Galaris', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect.poll(async () => (await bounds()).chrome.visible).toBe(true)
  await shortcut('Tab', ['control', 'shift'])
  await expect.poll(bounds).toMatchObject({ chrome: { visible: false }, page: { y: 0 } })
  await first.getByRole('button', { name: 'Close full screen preview' }).click()
  await expect.poll(async () => (await bounds()).chrome.visible).toBe(true)
  await expect.poll(async () => (await bounds()).page.y).toBeGreaterThan(0)
  await client!.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'about:blank#galaris-workspace')!.setSize(1280, 900))
  await expect(first.locator('html')).toHaveAttribute('data-galaris-desktop-shell', '')
  await first.getByRole('link', { name: 'Leave shell' }).click()
  await expect(first).toHaveURL(`${origin}/second`)
  await expect.poll(async () => client!.evaluate(({ BrowserWindow, WebContentsView }) => {
    const owner = BrowserWindow.getAllWindows().find(win => win.webContents.getURL() === 'about:blank#galaris-workspace')!
    const chrome = owner.contentView.children.find(view => view instanceof WebContentsView && view.webContents.getURL().endsWith('?tabs')) as Electron.WebContentsView
    return chrome.getBounds().x
  })).toBe(0)
  await chrome.getByRole('button', { name: 'Back', exact: true }).click()
  await expect(first.locator('html')).toHaveAttribute('data-galaris-desktop-shell', '')
  await expect.poll(async () => (await bounds()).chrome.x).toBe(await padding())
  expect((await bounds()).page.y).toBe(0)
  expect(await first.evaluate(() => typeof window.galarisDesktop)).toBe('undefined')
})

test('French and English spellchecking exposes suggestions and dictionary actions in the native menu', async () => {
  const remote = await openServer(await launch())
  const configuration = await client!.evaluate(({ webContents }) => {
    const contents = webContents.getAllWebContents().find(page => page.getURL().startsWith('http:'))!
    return { enabled: contents.session.isSpellCheckerEnabled(), languages: contents.session.getSpellCheckerLanguages() }
  })
  expect(configuration.enabled).toBe(true)
  expect(configuration.languages).toEqual(expect.arrayContaining(['fr', 'en-US']))
  // Replace only the native popup boundary; Chromium still emits the real right-click.
  await client!.evaluate(({ Menu, webContents }) => {
    const contents = webContents.getAllWebContents().find(page => page.getURL().startsWith('http:'))!
    contents.prependListener('context-menu', (_event, params) => {
      params.misspelledWord = 'synthetci'
      params.dictionarySuggestions = ['synthetic']
    })
    const tracker = { labels: [] as string[], add: undefined as (() => void) | undefined }
    ;(globalThis as unknown as { spellingTest: typeof tracker }).spellingTest = tracker
    Menu.prototype.popup = function () {
      tracker.labels = this.items.map(item => item.label)
      tracker.add = () => { this.items.find(item => item.label === 'Add to dictionary')!.click() }
    }
  })
  await remote.getByRole('textbox', { name: 'Draft' }).fill('synthetci')
  await remote.getByRole('textbox', { name: 'Draft' }).click({ button: 'right' })
  await expect.poll(() => client!.evaluate(() => (globalThis as unknown as { spellingTest: { labels: string[] } }).spellingTest.labels)).toEqual(expect.arrayContaining(['synthetic', 'Add to dictionary']))
  await client!.evaluate(() => (globalThis as unknown as { spellingTest: { add: () => void } }).spellingTest.add())
  await expect.poll(() => client!.evaluate(async ({ webContents }) => webContents.getAllWebContents().find(page => page.getURL().startsWith('http:'))!.session.listWordsInSpellCheckerDictionary())).toContain('synthetci')
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
