import { BrowserWindow, desktopCapturer, ipcMain } from 'electron'
import type { Locale, ScreenRequest } from './contracts.ts'
import { remotePreferences } from './policy.ts'

export const screenURL = 'galaris-desktop://launcher/index.html?screenshot'
export const screenMaxBytes = 1_500_000

interface PendingScreen {
  window: BrowserWindow
  request: ScreenRequest
  finish: (image: ArrayBuffer | null) => void
  sources: Electron.DesktopCapturerSource[]
  selected: Electron.DesktopCapturerSource | undefined
  captured: boolean
  signal: AbortSignal
}

export class ScreenPrompt {
  private pending: PendingScreen | undefined
  private readonly session: Electron.Session
  private readonly preload: string
  private readonly nativePicker = process.platform === 'linux'
    && (process.env.XDG_SESSION_TYPE === 'wayland' || Boolean(process.env.WAYLAND_DISPLAY))

  constructor(session: Electron.Session, preload: string, locale: Locale, title: string) {
    this.session = session
    this.preload = preload
    const permission = (contents: Electron.WebContents | null, kind: string, main: boolean) =>
      kind === 'display-capture' && main && Boolean(contents && this.owns(contents)
        && (this.nativePicker || this.pending?.selected))
    session.setPermissionRequestHandler((contents, kind, callback, details) => callback(permission(contents, kind, details.isMainFrame)))
    session.setPermissionCheckHandler((contents, kind, _origin, details) => permission(contents, kind, details.isMainFrame))
    session.setDisplayMediaRequestHandler((request, callback) => {
      const pending = this.pending
      if (!pending || pending.window.isDestroyed() || !this.owns(pending.window.webContents) || (!this.nativePicker && !pending.selected)
        || request.frame !== pending.window.webContents.mainFrame || !request.userGesture
        || request.audioRequested || !request.videoRequested) { callback(null); return }
      const grant = (source: Electron.DesktopCapturerSource | undefined) => {
        if (!source || this.pending !== pending || pending.window.isDestroyed() || !this.owns(pending.window.webContents)) {
          callback(null)
          return
        }
        pending.selected = undefined
        pending.captured = true
        pending.window.hide()
        callback({ video: source })
      }
      if (this.nativePicker) {
        void desktopCapturer.getSources({ types: ['screen', 'window'], thumbnailSize: { width: 0, height: 0 } })
          .then(sources => grant(sources.length === 1 ? sources[0] : undefined), () => callback(null))
      } else grant(pending.selected)
    })
    ipcMain.handle('desktop:screen-state', event => ({
      ...this.authorize(event).request, locale, title, nativePicker: this.nativePicker,
    }))
    ipcMain.handle('desktop:screen-sources', async event => {
      const pending = this.authorize(event)
      const types: ('screen' | 'window')[][] = [['screen'], ['window']]
      // A window enumeration can be empty even when a usable screen exists.
      const results = await Promise.allSettled(types.map(kind =>
        desktopCapturer.getSources({ types: kind, thumbnailSize: { width: 0, height: 0 } })))
      const sources = results.flatMap(result => result.status === 'fulfilled' ? result.value : [])
      if (pending !== this.pending || pending.signal.aborted) return []
      const ownSource = pending.window.getMediaSourceId()
      pending.sources = sources.filter(source => source.id !== ownSource).slice(0, 200)
      return pending.sources.map(source => ({ id: source.id, name: source.name.slice(0, 240) }))
    })
    ipcMain.handle('desktop:screen-select', (event, id: unknown) => {
      const pending = this.authorize(event)
      pending.selected = pending.sources.find(source => source.id === id)
      return Boolean(pending.selected)
    })
    ipcMain.handle('desktop:screen-restore', event => this.authorize(event).window.show())
    ipcMain.handle('desktop:screen-finish', (event, image: unknown) => {
      const pending = this.authorize(event)
      if (image === null) { pending.finish(null); return }
      if (!pending.captured || !(image instanceof ArrayBuffer) || !image.byteLength || image.byteLength > screenMaxBytes) {
        throw new Error('Invalid screen capture')
      }
      pending.finish(image)
    })
  }

  private owns(contents: Electron.WebContents): boolean {
    const item = this.pending
    return Boolean(item && !item.signal.aborted && !item.window.isDestroyed()
      && item.window.webContents === contents && contents.getURL() === screenURL)
  }

  private authorize(event: Electron.IpcMainInvokeEvent): PendingScreen {
    if (!this.pending || !this.owns(event.sender) || event.senderFrame !== event.sender.mainFrame) {
      throw new Error('Unauthorized screen capture request')
    }
    return this.pending
  }

  open(parent: BrowserWindow, request: ScreenRequest, signal: AbortSignal, title: string): Promise<ArrayBuffer | null> {
    if (this.pending || signal.aborted || parent.isDestroyed()) return Promise.resolve(null)
    const window = new BrowserWindow({ parent, modal: true, show: false, title, width: 690, height: 680,
      minWidth: 420, minHeight: 400, autoHideMenuBar: true,
      webPreferences: { ...remotePreferences, session: this.session, preload: this.preload, backgroundThrottling: false } })
    window.webContents.on('will-navigate', event => event.preventDefault())
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    return new Promise(resolve => {
      const onAbort = () => finish(null)
      const finish = (image: ArrayBuffer | null) => {
        if (this.pending?.window !== window) return
        this.pending = undefined
        signal.removeEventListener('abort', onAbort)
        resolve(image)
        setImmediate(() => { if (!window.isDestroyed()) window.destroy() })
      }
      this.pending = { window, request, finish, sources: [], selected: undefined, captured: false, signal }
      signal.addEventListener('abort', onAbort, { once: true })
      window.once('closed', () => finish(null))
      window.once('ready-to-show', () => { if (!window.isDestroyed() && !signal.aborted) window.show() })
      void window.loadURL(screenURL).catch(() => finish(null))
    })
  }
}
