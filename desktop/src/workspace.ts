import { BrowserWindow, Menu, shell, WebContentsView } from 'electron'
import { externalURL, remotePreferences, sameOrigin } from './policy.ts'
import { tabBarHeight, workspaceURL } from './layout.ts'
import { readShellLayout, shellScript, type ShellLayout } from './shell.ts'
import type { TabsState } from './contracts.ts'

export const tabsURL = 'galaris-desktop://launcher/index.html?tabs'
type Translate = (key: 'newTab' | 'closeTab' | 'tabs' | 'openInTab' | 'addToDictionary' | 'noSuggestions') => string

/** Local chrome owns the views; server content never receives a preload or IPC bridge. */
export class Workspace {
  readonly chrome: WebContentsView
  private views = new Map<number, WebContentsView>()
  private shells = new Map<number, ShellLayout>()
  private activeId = 0
  private closing: Promise<boolean> | undefined
  private readonly pendingCloses = new WeakMap<Electron.WebContents, Promise<boolean>>()
  private destroying = false

  constructor(
    readonly window: BrowserWindow,
    readonly origin: string,
    private readonly session: Electron.Session,
    private readonly t: Translate,
    private readonly blocked: () => void,
    private readonly failed: () => void,
    chromePreferences: Electron.WebPreferences
  ) {
    this.chrome = new WebContentsView({ webPreferences: chromePreferences })
    window.contentView.addChildView(this.chrome)
    this.chrome.webContents.on('will-navigate', event => event.preventDefault())
    this.chrome.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    this.shortcuts(this.chrome.webContents)
    window.on('resize', () => this.layout())
    window.on('close', event => { event.preventDefault(); void this.close() })
    window.on('closed', () => this.destroyViews())
    window.webContents.on('will-navigate', event => event.preventDefault())
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    this.shortcuts(window.webContents)
  }

  get active(): Electron.WebContents | undefined { return this.views.get(this.activeId)?.webContents }
  owns(contents: Electron.WebContents): boolean { return this.views.has(contents.id) }
  snapshot(): TabsState {
    const shell = this.shells.get(this.activeId)
    return { activeId: this.activeId,
      dark: shell?.integrated ? shell.dark : null,
      surface: shell?.integrated ? shell.surface : 'rgb(255, 255, 255)',
      canGoBack: this.active?.navigationHistory.canGoBack() ?? false,
      canGoForward: this.active?.navigationHistory.canGoForward() ?? false,
      tabs: [...this.views.values()].map(({ webContents: contents }) => ({
      id: contents.id, title: contents.getTitle() || this.t('newTab'), loading: contents.isLoading()
    })) }
  }
  private changed(): void {
    if (!this.window.isDestroyed() && !this.chrome.webContents.isDestroyed()) this.chrome.webContents.send('desktop:tabs-changed', this.snapshot())
  }
  private layout(): void {
    if (this.window.isDestroyed()) return
    const { width, height } = this.window.getContentBounds()
    for (const [id, view] of this.views) {
      const zoom = view.webContents.getZoomFactor()
      const shell = this.shells.get(id)
      const integrated = shell?.integrated && width / zoom >= 1024
      const top = integrated || shell?.fullscreen ? 0 : Math.round(tabBarHeight * zoom)
      view.setBounds({ x: 0, y: top, width, height: Math.max(0, height - top) })
    }
    const zoom = this.active?.getZoomFactor() ?? 1
    const shell = this.shells.get(this.activeId)
    const left = shell?.integrated && width / zoom >= 1024 ? Math.min(Math.round(shell.left * zoom), Math.max(0, width - 240)) : 0
    this.chrome.webContents.setZoomFactor(zoom)
    this.chrome.setBounds({ x: left, y: 0, width: width - left, height: Math.round(tabBarHeight * zoom) })
    this.chrome.setVisible(!shell?.fullscreen)
  }
  select(id: number): void {
    if (!this.views.has(id)) return
    this.activeId = id
    for (const [key, view] of this.views) view.setVisible(key === id)
    this.layout()
    this.active?.focus()
    this.changed()
  }
  cycle(offset: number): void {
    const ids = [...this.views.keys()]
    const id = ids[(ids.indexOf(this.activeId) + offset + ids.length) % ids.length]
    if (id !== undefined) this.select(id)
  }
  back(): void {
    if (this.active?.navigationHistory.canGoBack()) { this.active.navigationHistory.goBack(); this.active.focus() }
  }
  forward(): void {
    if (this.active?.navigationHistory.canGoForward()) { this.active.navigationHistory.goForward(); this.active.focus() }
  }
  reload(): void {
    const contents = this.active
    if (!this.closing && contents && !this.pendingCloses.has(contents)) contents.reload()
  }
  showMenu(): void {
    this.active?.focus()
    const bounds = this.chrome.getBounds()
    Menu.getApplicationMenu()?.popup({ window: this.window, x: bounds.x + 4, y: bounds.height })
  }
  private create(background = false): WebContentsView {
    const view = new WebContentsView({ webPreferences: { ...remotePreferences, session: this.session } })
    const contents = view.webContents
    const id = contents.id
    this.views.set(id, view)
    this.window.contentView.addChildView(view, 0)
    view.setVisible(false)
    this.guard(contents, true)
    this.shortcuts(contents)
    contents.on('console-message', details => {
      if (details.frame !== contents.mainFrame || !sameOrigin(contents.getURL(), this.origin)) return
      const shell = readShellLayout(details.message)
      if (!shell) return
      this.shells.set(id, shell)
      this.layout()
      this.changed()
    })
    contents.on('dom-ready', () => {
      if (!sameOrigin(contents.getURL(), this.origin)) return
      void contents.executeJavaScriptInIsolatedWorld(1001, [{ code: shellScript }]).catch(() => {
        if (!contents.isDestroyed()) { this.shells.delete(id); this.layout(); this.changed() }
      })
    })
    contents.on('did-start-navigation', (_event, _url, inPlace, mainFrame) => {
      if (mainFrame && !inPlace) { this.shells.delete(id); this.layout(); this.changed() }
    })
    contents.on('page-title-updated', () => this.changed())
    contents.on('did-start-loading', () => this.changed())
    contents.on('did-stop-loading', () => this.changed())
    contents.on('did-navigate', () => this.changed())
    contents.on('did-navigate-in-page', (_event, _url, isMainFrame) => { if (isMainFrame) this.changed() })
    contents.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
      if (mainFrame && code !== -3 && !this.destroying) this.failed()
    })
    contents.on('render-process-gone', () => { if (!this.destroying) this.failed() })
    contents.on('destroyed', () => {
      if (!this.window.isDestroyed()) this.window.contentView.removeChildView(view)
      const ids = [...this.views.keys()]
      const index = ids.indexOf(id)
      this.views.delete(id)
      this.shells.delete(id)
      if (this.destroying) return
      if (this.activeId === id) this.select(ids[index + 1] ?? ids[index - 1] ?? 0)
      this.changed()
      if (!this.views.size && !this.closing) void this.close()
    })
    if (!background || !this.active) this.select(contents.id)
    else { this.layout(); this.changed() }
    return view
  }
  async open(url = `${this.origin}/`, background = false): Promise<void> {
    if (this.closing || this.destroying || !sameOrigin(url, this.origin)) return
    const view = this.create(background)
    try { await view.webContents.loadURL(url) } catch { /* did-fail-load reports failures; the tab remains retryable. */ }
  }
  async load(): Promise<void> {
    await this.window.loadURL(workspaceURL)
    await this.chrome.webContents.loadURL(tabsURL)
    const view = this.create()
    await view.webContents.loadURL(`${this.origin}/`)
    if (!sameOrigin(view.webContents.getURL(), this.origin)) throw new Error('connectionFailed')
  }
  private closeContents(contents: Electron.WebContents): Promise<boolean> {
    if (contents.isDestroyed()) return Promise.resolve(true)
    const pending = this.pendingCloses.get(contents)
    if (pending) return pending
    const close = new Promise<boolean>(resolve => {
      const cleanup = () => { contents.removeListener('destroyed', closed); contents.removeListener('will-prevent-unload', blocked) }
      const closed = () => { cleanup(); resolve(true) }
      // Navigation and automatic reloads can also be vetoed by beforeunload.
      const blocked = () => {
        cleanup()
        resolve(false)
        this.select(contents.id)
        this.blocked()
      }
      contents.once('destroyed', closed)
      contents.once('will-prevent-unload', blocked)
    })
    this.pendingCloses.set(contents, close)
    contents.close({ waitForBeforeUnload: true })
    void close.then(() => this.pendingCloses.delete(contents))
    return close
  }
  async closeTab(id = this.activeId): Promise<void> {
    if (this.closing) return
    const contents = this.views.get(id)?.webContents
    if (contents) await this.closeContents(contents)
  }
  close(): Promise<boolean> {
    if (this.closing) return this.closing
    this.closing = Promise.resolve().then(async () => {
      // Ask the active page first; every remaining page also keeps its unload protection.
      const contents = [...this.views.values()].map(view => view.webContents)
      contents.sort((left, right) => Number(right.id === this.activeId) - Number(left.id === this.activeId))
      for (const page of contents) if (!await this.closeContents(page)) return false
      this.destroy()
      return true
    })
    void this.closing.then(closed => { if (!closed) this.closing = undefined })
    return this.closing
  }
  private destroyViews(): void {
    this.destroying = true
    for (const view of [...this.views.values()]) view.webContents.close()
    this.views.clear()
    this.shells.clear()
    if (!this.chrome.webContents.isDestroyed()) this.chrome.webContents.close()
  }
  destroy(): void { this.destroyViews(); if (!this.window.isDestroyed()) this.window.destroy() }

  private shortcuts(contents: Electron.WebContents): void {
    // Chromium can consume tab shortcuts before native menu accelerators in a view.
    contents.on('before-input-event', (event, input) => {
      if (input.type !== 'keyDown') return
      const primary = process.platform === 'darwin' ? input.meta : input.control
      const key = input.key.toLowerCase()
      if (primary && !input.alt && !input.shift && ['t', 'w'].includes(key)) {
        event.preventDefault()
        if (!input.isAutoRepeat) {
          if (key === 't') void this.open()
          else void this.closeTab()
        }
      } else if (input.control && !input.alt && ['tab', 'pageup', 'pagedown'].includes(key)) {
        event.preventDefault()
        this.cycle(key === 'pageup' || (key === 'tab' && input.shift) ? -1 : 1)
      }
    })
  }

  private guard(contents: Electron.WebContents, previews: boolean): void {
    contents.on('will-attach-webview', event => event.preventDefault())
    const safe = (url: string): boolean => {
      if (sameOrigin(url, this.origin)) return true
      try {
        const target = new URL(url)
        return (target.protocol === 'https:' && !target.username && !target.password)
          || url === 'about:blank' || url.startsWith(`blob:${this.origin}/`) || url.startsWith('data:')
      } catch { return false }
    }
    contents.on('will-navigate', (event, url) => { if (!safe(url)) event.preventDefault() })
    contents.on('will-redirect', (event, url) => { if (!safe(url)) event.preventDefault() })
    contents.setWindowOpenHandler(({ url, disposition }) => {
      if (previews && sameOrigin(url, this.origin) && !this.closing) {
        // Galaris opens resource links with noopener. Schedule our own view after the
        // synchronous new-window request has returned, retaining the same isolation.
        setImmediate(() => { void this.open(url, disposition === 'background-tab') })
        return { action: 'deny' }
      }
      if (previews && (url === 'about:blank' || url.startsWith(`blob:${this.origin}/`) || url.startsWith('data:'))) {
        return { action: 'allow', overrideBrowserWindowOptions: {
          parent: this.window, autoHideMenuBar: true,
          webPreferences: { ...remotePreferences, session: this.session }
        } }
      }
      const target = externalURL(url)
      if (target) void shell.openExternal(target).catch(() => undefined)
      return { action: 'deny' }
    })
    contents.on('did-create-window', child => this.guard(child.webContents, false))
    contents.on('context-menu', (_event, params) => {
      const items: Electron.MenuItemConstructorOptions[] = []
      if (previews && sameOrigin(params.linkURL, this.origin)) {
        items.push({ label: this.t('openInTab'), click: () => { void this.open(params.linkURL, true) } }, { type: 'separator' })
      }
      if (params.misspelledWord) {
        for (const word of params.dictionarySuggestions) items.push({ label: word, click: () => contents.replaceMisspelling(word) })
        if (!params.dictionarySuggestions.length) items.push({ label: this.t('noSuggestions'), enabled: false })
        items.push({ label: this.t('addToDictionary'), click: () => contents.session.addWordToSpellCheckerDictionary(params.misspelledWord) }, { type: 'separator' })
      }
      if (params.isEditable) items.push({ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' })
      else if (params.selectionText) items.push({ role: 'copy' })
      if (items.length) Menu.buildFromTemplate(items).popup({ window: this.window })
    })
  }
}
