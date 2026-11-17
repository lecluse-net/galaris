import { app, BrowserWindow, dialog, ipcMain, Menu, net, protocol, session } from 'electron'
import { autoUpdater } from 'electron-updater'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { readServer, writeServer } from './preferences.ts'
import { partitionFor, remotePreferences, sameOrigin, serverOrigin } from './policy.ts'
import { Workspace, tabsURL } from './workspace.ts'
import { configureUpdates } from './updates.ts'
import type { DesktopState, Locale } from './contracts.ts'
import messages from '../renderer/messages.json'
import { writeFailure } from './diagnostics.ts'

const launcherURL = 'galaris-desktop://launcher/index.html'
protocol.registerSchemesAsPrivileged([{ scheme: 'galaris-desktop', privileges: { standard: true, secure: true } }])
app.setName('Galaris')
app.setAppUserModelId('net.lecluse.galaris')
// Isolated test profiles are accepted only by unbundled development builds.
if (!app.isPackaged && process.env.GALARIS_DESKTOP_USER_DATA) app.setPath('userData', process.env.GALARIS_DESKTOP_USER_DATA)

let launcher: BrowserWindow
let remote: Workspace | undefined
let candidate: Workspace | undefined
let generation = 0
let quitting = false
let installing = false
let state: DesktopState
let updates: ReturnType<typeof configureUpdates>
let interval: NodeJS.Timeout | undefined

function t(key: keyof typeof messages.en, parameters: Record<string, string> = {}): string {
  let value: string = messages[state?.locale ?? 'en'][key]
  for (const [name, replacement] of Object.entries(parameters)) value = value.replaceAll(`{${name}}`, replacement)
  return value
}
function broadcast(): void {
  if (launcher && !launcher.isDestroyed()) launcher.webContents.send('desktop:changed', state)
}
function showLauncher(): void {
  launcher.show()
  launcher.focus()
  broadcast()
}
function recordFailure(stage: string, error: unknown): boolean {
  try { writeFailure(app.getPath('userData'), app.getVersion(), stage, error); return true } catch {
    if (state) { state.diagnosticsFailed = true; broadcast() }
    return false
  }
}
function cancel(): void {
  generation++
  const pending = candidate
  candidate = undefined
  pending?.destroy()
  state.connecting = false
  broadcast()
}

function authorize(event: Electron.IpcMainInvokeEvent, workspace = false): void {
  const contents = workspace ? [remote, candidate].find(item => item?.chrome.webContents === event.sender)?.chrome.webContents : launcher?.webContents
  if (!contents || event.sender !== contents || event.senderFrame !== contents.mainFrame || event.senderFrame.url !== (workspace ? tabsURL : launcherURL)) {
    throw new Error('Unauthorized desktop request')
  }
}

function configureSession(origin: string): Electron.Session {
  const ses = session.fromPartition(partitionFor(origin))
  ses.setSpellCheckerEnabled(true)
  if (process.platform !== 'darwin') ses.setSpellCheckerLanguages(['fr', 'en-US'].filter(language => ses.availableSpellCheckerLanguages.includes(language)))
  // Replacing handlers prevents accumulation when the same server is reopened.
  const granted = new Set<string>()
  const pending = new Map<string, Promise<boolean>>()
  const allowed = new Map([['media', 'media'], ['notifications', 'notifications'], ['clipboard-read', 'clipboardRead']] as const)
  const standard = new Set(['clipboard-sanitized-write', 'fullscreen'])
  ses.setPermissionCheckHandler((contents, permission, requestingOrigin, details) => (
    Boolean(contents && sameOrigin(contents.getURL(), origin) && sameOrigin(requestingOrigin, origin)
      && details.isMainFrame && (standard.has(permission) || granted.has(permission)))
  ))
  ses.setPermissionRequestHandler((contents, permission, callback, details) => {
    if (!contents || !sameOrigin(contents.getURL(), origin) || !details.isMainFrame || !sameOrigin(details.requestingUrl, origin)) {
      callback(false)
      return
    }
    if (standard.has(permission)) { callback(true); return }
    const label = allowed.get(permission as 'media' | 'notifications' | 'clipboard-read')
    if (!label) { callback(false); return }
    if (granted.has(permission)) { callback(true); return }
    let request = pending.get(permission)
    if (!request) {
      const owner = BrowserWindow.fromWebContents(contents) ?? [remote, candidate].find(item => item?.owns(contents))?.window
      if (!owner) { callback(false); return }
      request = dialog.showMessageBox(owner, {
        type: 'question', title: t('permissionTitle'),
        message: t('permission', { origin, capability: t(label) }),
        buttons: [t('deny'), t('allow')], defaultId: 0, cancelId: 0, noLink: true
      }).then(result => {
        const accepted = result.response === 1 && !contents.isDestroyed() && sameOrigin(contents.getURL(), origin)
        if (accepted) granted.add(permission)
        return accepted
      }).catch(() => false).finally(() => pending.delete(permission))
      pending.set(permission, request)
    }
    void request.then(callback)
  })
  return ses
}

async function connect(input: unknown): Promise<void> {
  if (state.connecting) return
  let origin: string
  try { origin = serverOrigin(input, !app.isPackaged) } catch {
    state.error = 'invalidServer'; broadcast(); return
  }
  state.error = ''
  state.connecting = true
  const attempt = ++generation
  broadcast()
  const window = new BrowserWindow({
    width: 1280, height: 900, minWidth: 480, minHeight: 480, show: false, title: 'Galaris', autoHideMenuBar: true,
    icon: app.isPackaged ? path.join(process.resourcesPath, 'icon.png') : path.join(__dirname, '../../front/public/pwa/icon-512.png'),
    webPreferences: { ...remotePreferences, session: launcher.webContents.session }
  })
  const win = new Workspace(window, origin, configureSession(origin), t, () => {
    quitting = false
    installing = false
    state.error = 'unsavedChanges'
    showLauncher()
  }, () => { if (remote === win) { state.error = 'connectionFailed'; showLauncher() } },
  { ...remotePreferences, session: launcher.webContents.session, preload: path.join(__dirname, 'preload.cjs') })
  candidate = win
  // A stalled DNS/TLS connection must remain cancellable and recover to the launcher.
  const timeout = setTimeout(() => {
    if (candidate !== win || attempt !== generation) return
    generation++
    candidate = undefined
    state.connecting = false
    state.error = 'connectionFailed'
    win.destroy()
    showLauncher()
  }, 30_000)
  try {
    await win.load()
    if (attempt !== generation || window.isDestroyed()) return
    if (remote && !remote.window.isDestroyed() && !await remote.close()) {
      if (attempt === generation) { candidate = undefined; state.connecting = false; showLauncher() }
      win.destroy()
      return
    }
    if (attempt !== generation || window.isDestroyed()) return
    // Commit the tiny preference atomically without yielding to a cancelled attempt.
    try { writeServer(app.getPath('userData'), origin) } catch {
      if (attempt === generation) state.error = 'saveFailed'
      throw new Error('saveFailed')
    }
    if (attempt !== generation || window.isDestroyed()) return
    remote = win
    candidate = undefined
    state.server = origin
    state.connecting = false
    window.on('closed', () => {
      if (remote !== win) return
      remote = undefined
      if (installing) { installing = false; showLauncher(); updates.install(); return }
      if (quitting) { setImmediate(() => app.quit()); return }
      if (!quitting && (launcher.isDestroyed() || !launcher.isVisible())) app.quit()
    })
    window.show()
    launcher.hide()
  } catch {
    if (attempt === generation) {
      if (!state.error) state.error = 'connectionFailed'
      state.connecting = false
      candidate = undefined
      showLauncher()
    }
    if (!window.isDestroyed()) win.destroy()
  } finally {
    clearTimeout(timeout)
    broadcast()
  }
}

function buildMenu(): void {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: t('appMenu'), submenu: [
      { label: t('changeServer'), accelerator: 'CmdOrCtrl+,', click: showLauncher },
      { label: t('check'), click: () => { showLauncher(); void updates.check() } },
      { type: 'separator' }, { label: t('quit'), accelerator: 'CmdOrCtrl+Q', click: () => app.quit() }
    ] },
    { role: 'editMenu' },
    { label: t('tabs'), submenu: [
      { label: t('newTab'), accelerator: 'CmdOrCtrl+T', click: () => { void remote?.open() } },
      { label: t('closeTab'), accelerator: 'CmdOrCtrl+W', click: () => { void remote?.closeTab() } },
      { label: t('nextTab'), accelerator: 'Ctrl+Tab', click: () => remote?.cycle(1) },
      { label: t('previousTab'), accelerator: 'Ctrl+Shift+Tab', click: () => remote?.cycle(-1) }
    ] },
    { label: t('view'), submenu: [
      { label: t('reload'), accelerator: 'CmdOrCtrl+R', click: () => remote?.active?.reload() },
      { label: t('back'), accelerator: 'Alt+Left', click: () => remote?.back() },
      { label: t('forward'), accelerator: 'Alt+Right', click: () => remote?.forward() },
      { label: t('resetZoom'), role: 'resetZoom' }, { label: t('zoomIn'), role: 'zoomIn' }, { label: t('zoomOut'), role: 'zoomOut' },
      { label: t('fullScreen'), role: 'togglefullscreen' }
    ] }
  ]))
}

async function start(): Promise<void> {
  const language = app.getLocale().split('-')[0]
  const locale: Locale = language === 'fr' || language === 'zh' ? language : 'en'
  state = {
    server: await readServer(app.getPath('userData'), !app.isPackaged), locale, version: app.getVersion(),
    error: '', connecting: false, diagnosticsFailed: false, update: { status: 'disabled', percent: 0, version: '' }
  }
  const localSession = session.fromPartition('launcher')
  localSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  localSession.setPermissionCheckHandler(() => false)
  const root = path.resolve(__dirname, '../dist')
  localSession.protocol.handle('galaris-desktop', request => {
    const url = new URL(request.url)
    const file = path.resolve(root, `.${decodeURIComponent(url.pathname)}`)
    if (url.host !== 'launcher' || !file.startsWith(`${root}${path.sep}`)) return new Response(null, { status: 404 })
    return net.fetch(pathToFileURL(file).href)
  })
  launcher = new BrowserWindow({
    width: 720, height: 720, minWidth: 420, minHeight: 520, show: false, title: 'Galaris',
    webPreferences: { ...remotePreferences, session: localSession, preload: path.join(__dirname, 'preload.cjs') }
  })
  launcher.webContents.on('will-navigate', event => event.preventDefault())
  launcher.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  launcher.on('close', event => {
    cancel()
    if (!quitting && remote && !remote.window.isDestroyed()) { event.preventDefault(); launcher.hide(); remote.window.show() }
  })
  ipcMain.handle('desktop:state', event => { authorize(event, event.sender !== launcher.webContents); return state })
  ipcMain.handle('desktop:tabs', event => { authorize(event, true); return (remote?.chrome.webContents === event.sender ? remote : candidate)?.snapshot() })
  ipcMain.handle('desktop:new-tab', event => { authorize(event, true); void remote?.open() })
  ipcMain.handle('desktop:select-tab', (event, id: unknown) => { authorize(event, true); if (typeof id === 'number') remote?.select(id) })
  ipcMain.handle('desktop:close-tab', (event, id: unknown) => { authorize(event, true); if (typeof id === 'number') return remote?.closeTab(id) })
  ipcMain.handle('desktop:back', event => { authorize(event, true); remote?.back() })
  ipcMain.handle('desktop:forward', event => { authorize(event, true); remote?.forward() })
  ipcMain.handle('desktop:show-menu', event => { authorize(event, true); remote?.showMenu() })
  ipcMain.handle('desktop:connect', (event, server: unknown) => { authorize(event); return connect(server) })
  ipcMain.handle('desktop:cancel', event => { authorize(event); cancel() })
  ipcMain.handle('desktop:check-updates', event => { authorize(event); return updates.check() })
  ipcMain.handle('desktop:install-update', event => { authorize(event); return confirmInstall() })
  const enabled = app.isPackaged && (process.platform === 'win32' || (process.platform === 'linux' && Boolean(process.env.APPIMAGE)))
  autoUpdater.logger = null
  autoUpdater.on('error', error => {
    recordFailure(`update:${state.update.status}`, error)
    if (state.update.status === 'ready') { state.error = 'updateFailed'; showLauncher() }
  })
  updates = configureUpdates(autoUpdater, enabled ? 'idle' : app.isPackaged ? 'manual' : 'disabled', update => {
    state.update = update; broadcast()
  }, () => { void confirmInstall() })
  buildMenu()
  await launcher.loadURL(launcherURL)
  showLauncher()
  if (state.server) void connect(state.server)
  if (enabled) {
    void updates.check()
    interval = setInterval(() => { void updates.check() }, 6 * 60 * 60 * 1000)
    interval.unref()
  }
}

let prompting = false
async function confirmInstall(): Promise<void> {
  if (prompting || state.update.status !== 'ready') return
  prompting = true
  try {
    const owner = remote && !remote.window.isDestroyed() ? remote.window : launcher
    const result = await dialog.showMessageBox(owner, {
      type: 'info', title: t('updates'), message: t('updateReady'),
      buttons: [t('later'), t('restart')], defaultId: 0, cancelId: 0, noLink: true
    })
    if (result.response === 1) {
      if (remote && !remote.window.isDestroyed()) { installing = true; void remote.close() }
      else updates.install()
    }
  } catch (error) { recordFailure('update:restart', error) } finally { prompting = false }
}

if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', () => {
    const win = remote?.window ?? launcher
    if (!win || win.isDestroyed()) return
    if (win.isMinimized()) win.restore()
    win.show(); win.focus()
  })
  app.on('before-quit', event => {
    quitting = true
    if (remote && !remote.window.isDestroyed()) { event.preventDefault(); void remote.close(); return }
    clearInterval(interval)
  })
  app.on('window-all-closed', () => app.quit())
  void app.whenReady().then(start).catch(error => {
    const stored = recordFailure('startup', error)
    dialog.showErrorBox('Galaris', `${t('startupFailed')}${stored ? '' : `\n${t('diagnosticsFailed')}`}`)
    app.quit()
  })
}
