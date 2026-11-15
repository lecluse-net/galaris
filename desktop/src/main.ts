import { app, BrowserWindow, dialog, ipcMain, Menu, net, protocol, session, shell } from 'electron'
import { autoUpdater } from 'electron-updater'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { readServer, writeServer } from './preferences.ts'
import { externalURL, partitionFor, remotePreferences, sameOrigin, serverOrigin } from './policy.ts'
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
let remote: BrowserWindow | undefined
let candidate: BrowserWindow | undefined
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

function authorize(event: Electron.IpcMainInvokeEvent): void {
  if (event.sender !== launcher.webContents || event.senderFrame !== launcher.webContents.mainFrame || event.senderFrame.url !== launcherURL) {
    throw new Error('Unauthorized desktop request')
  }
}

function configureSession(origin: string): Electron.Session {
  const ses = session.fromPartition(partitionFor(origin))
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
      const owner = BrowserWindow.fromWebContents(contents)
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

function guardWindow(win: BrowserWindow, origin: string, previews = true): void {
  win.webContents.on('will-prevent-unload', () => {
    if (remote !== win) return
    quitting = false
    installing = false
    state.error = 'unsavedChanges'
    showLauncher()
  })
  win.webContents.on('will-attach-webview', event => event.preventDefault())
  const safeNavigation = (url: string): boolean => {
    if (sameOrigin(url, origin)) return true
    // HTTPS redirects in the same window preserve OAuth sessionStorage and callbacks.
    try {
      const target = new URL(url)
      return (target.protocol === 'https:' && !target.username && !target.password)
        || url === 'about:blank' || url.startsWith(`blob:${origin}/`) || url.startsWith('data:')
    } catch { return false }
  }
  win.webContents.on('will-navigate', (event, url) => { if (!safeNavigation(url)) event.preventDefault() })
  win.webContents.on('will-redirect', (event, url) => { if (!safeNavigation(url)) event.preventDefault() })
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (previews && (sameOrigin(url, origin) || url === 'about:blank' || url.startsWith(`blob:${origin}/`) || url.startsWith('data:'))) {
      return { action: 'allow', overrideBrowserWindowOptions: { autoHideMenuBar: true, webPreferences: { ...remotePreferences, session: win.webContents.session } } }
    }
    const target = externalURL(url)
    if (target) void shell.openExternal(target).catch(() => undefined)
    return { action: 'deny' }
  })
  win.webContents.on('did-create-window', child => guardWindow(child, origin, false))
}

function closeForSwitch(win: BrowserWindow): Promise<boolean> {
  return new Promise(resolve => {
    const contents = win.webContents
    const cleanup = () => {
      win.removeListener('closed', closed)
      contents.removeListener('will-prevent-unload', blocked)
    }
    const closed = () => { cleanup(); resolve(true) }
    const blocked = () => { cleanup(); resolve(false) }
    win.once('closed', closed)
    contents.once('will-prevent-unload', blocked)
    win.close()
  })
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
  const win = new BrowserWindow({
    width: 1280, height: 900, minWidth: 480, minHeight: 480, show: false, title: 'Galaris',
    icon: app.isPackaged ? path.join(process.resourcesPath, 'icon.png') : path.join(__dirname, '../../front/public/pwa/icon-512.png'),
    webPreferences: { ...remotePreferences, session: configureSession(origin) }
  })
  candidate = win
  guardWindow(win, origin)
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
    await win.loadURL(`${origin}/`)
    if (attempt !== generation || win.isDestroyed()) return
    // An initial cross-origin redirect must not silently select another server.
    if (!sameOrigin(win.webContents.getURL(), origin)) throw new Error('connectionFailed')
    if (remote && !remote.isDestroyed() && !await closeForSwitch(remote)) {
      if (attempt === generation) { candidate = undefined; state.connecting = false; showLauncher() }
      win.destroy()
      return
    }
    if (attempt !== generation || win.isDestroyed()) return
    // Commit the tiny preference atomically without yielding to a cancelled attempt.
    try { writeServer(app.getPath('userData'), origin) } catch {
      if (attempt === generation) state.error = 'saveFailed'
      throw new Error('saveFailed')
    }
    if (attempt !== generation || win.isDestroyed()) return
    remote = win
    candidate = undefined
    state.server = origin
    state.connecting = false
    win.on('closed', () => {
      if (remote !== win) return
      remote = undefined
      if (installing) { installing = false; showLauncher(); updates.install(); return }
      if (quitting) { setImmediate(() => app.quit()); return }
      if (!quitting && (launcher.isDestroyed() || !launcher.isVisible())) app.quit()
    })
    win.webContents.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
      if (remote === win && mainFrame && code !== -3) { state.error = 'connectionFailed'; showLauncher() }
    })
    win.webContents.on('render-process-gone', () => { if (remote === win) { state.error = 'connectionFailed'; showLauncher() } })
    win.show()
    launcher.hide()
  } catch {
    if (attempt === generation) {
      if (!state.error) state.error = 'connectionFailed'
      state.connecting = false
      candidate = undefined
      showLauncher()
    }
    if (!win.isDestroyed()) win.destroy()
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
    { label: t('view'), submenu: [
      { label: t('reload'), role: 'reload' },
      { label: t('back'), accelerator: 'Alt+Left', click: () => { if (remote?.webContents.navigationHistory.canGoBack()) remote.webContents.navigationHistory.goBack() } },
      { label: t('forward'), accelerator: 'Alt+Right', click: () => { if (remote?.webContents.navigationHistory.canGoForward()) remote.webContents.navigationHistory.goForward() } },
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
    if (!quitting && remote && !remote.isDestroyed()) { event.preventDefault(); launcher.hide(); remote.show() }
  })
  ipcMain.handle('desktop:state', event => { authorize(event); return state })
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
    const owner = remote && !remote.isDestroyed() ? remote : launcher
    const result = await dialog.showMessageBox(owner, {
      type: 'info', title: t('updates'), message: t('updateReady'),
      buttons: [t('later'), t('restart')], defaultId: 0, cancelId: 0, noLink: true
    })
    if (result.response === 1) {
      if (remote && !remote.isDestroyed()) { installing = true; remote.close() }
      else updates.install()
    }
  } catch (error) { recordFailure('update:restart', error) } finally { prompting = false }
}

if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', () => {
    const win = remote ?? launcher
    if (!win || win.isDestroyed()) return
    if (win.isMinimized()) win.restore()
    win.show(); win.focus()
  })
  app.on('before-quit', event => {
    quitting = true
    if (remote && !remote.isDestroyed()) { event.preventDefault(); remote.close(); return }
    clearInterval(interval)
  })
  app.on('window-all-closed', () => app.quit())
  void app.whenReady().then(start).catch(error => {
    const stored = recordFailure('startup', error)
    dialog.showErrorBox('Galaris', `${t('startupFailed')}${stored ? '' : `\n${t('diagnosticsFailed')}`}`)
    app.quit()
  })
}
