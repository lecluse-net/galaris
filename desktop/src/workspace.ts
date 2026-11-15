import { BrowserWindow, Menu, shell, WebContentsView } from 'electron'
import { externalURL, remotePreferences, sameOrigin } from './policy.ts'
import { tabBarHeight } from './layout.ts'
import type { TabsState } from './contracts.ts'

export const tabsURL = 'galaris-desktop://launcher/index.html?tabs'
type Translate = (key: 'newTab' | 'closeTab' | 'tabs' | 'openInTab' | 'addToDictionary' | 'noSuggestions') => string

/** Local chrome owns the views; server content never receives a preload or IPC bridge. */
export class Workspace {
  private views = new Map<number, WebContentsView>()
  private activeId = 0
  private closing: Promise<boolean> | undefined
  private destroying = false

  constructor(
    readonly window: BrowserWindow,
    readonly origin: string,
    private readonly session: Electron.Session,
    private readonly t: Translate,
    private readonly blocked: () => void,
    private readonly failed: () => void
  ) {
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
    return { activeId: this.activeId, tabs: [...this.views.values()].map(({ webContents: contents }) => ({
      id: contents.id, title: contents.getTitle() || this.t('newTab'), loading: contents.isLoading()
    })) }
  }
  private changed(): void {
    if (!this.window.isDestroyed()) this.window.webContents.send('desktop:tabs-changed', this.snapshot())
  }
  private layout(): void {
    if (this.window.isDestroyed()) return
    const { width, height } = this.window.getContentBounds()
    for (const view of this.views.values()) view.setBounds({ x: 0, y: tabBarHeight, width, height: Math.max(0, height - tabBarHeight) })
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
  private create(background = false): WebContentsView {
    const view = new WebContentsView({ webPreferences: { ...remotePreferences, session: this.session } })
    const contents = view.webContents
    const id = contents.id
    this.views.set(id, view)
    this.window.contentView.addChildView(view)
    view.setVisible(false)
    this.guard(contents, true)
    this.shortcuts(contents)
    contents.on('page-title-updated', () => this.changed())
    contents.on('did-start-loading', () => this.changed())
    contents.on('did-stop-loading', () => this.changed())
    contents.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
      if (mainFrame && code !== -3 && !this.destroying) this.failed()
    })
    contents.on('render-process-gone', () => { if (!this.destroying) this.failed() })
    contents.on('will-prevent-unload', () => { this.select(contents.id); this.blocked() })
    contents.on('destroyed', () => {
      if (!this.window.isDestroyed()) this.window.contentView.removeChildView(view)
      const ids = [...this.views.keys()]
      const index = ids.indexOf(id)
      this.views.delete(id)
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
    await this.window.loadURL(tabsURL)
    const view = this.create()
    await view.webContents.loadURL(`${this.origin}/`)
    if (!sameOrigin(view.webContents.getURL(), this.origin)) throw new Error('connectionFailed')
  }
  private closeContents(contents: Electron.WebContents): Promise<boolean> {
    if (contents.isDestroyed()) return Promise.resolve(true)
    return new Promise(resolve => {
      const cleanup = () => { contents.removeListener('destroyed', closed); contents.removeListener('will-prevent-unload', blocked) }
      const closed = () => { cleanup(); resolve(true) }
      const blocked = () => { cleanup(); resolve(false) }
      contents.once('destroyed', closed)
      contents.once('will-prevent-unload', blocked)
      contents.close({ waitForBeforeUnload: true })
    })
  }
  async closeTab(id = this.activeId): Promise<void> {
    if (this.closing) return
    const contents = this.views.get(id)?.webContents
    if (contents) await this.closeContents(contents)
  }
  close(): Promise<boolean> {
    if (this.closing) return this.closing
    this.closing = (async () => {
      // Ask the active page first; every remaining page also keeps its unload protection.
      const contents = [...this.views.values()].map(view => view.webContents)
      contents.sort((left, right) => Number(right.id === this.activeId) - Number(left.id === this.activeId))
      for (const page of contents) if (!await this.closeContents(page)) return false
      this.window.destroy()
      return true
    })()
    void this.closing.then(closed => { if (!closed) this.closing = undefined })
    return this.closing
  }
  private destroyViews(): void {
    this.destroying = true
    for (const view of [...this.views.values()]) view.webContents.close()
    this.views.clear()
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
