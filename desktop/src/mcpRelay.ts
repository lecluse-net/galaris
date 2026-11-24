import { randomBytes, randomUUID } from 'node:crypto'
import { readFile, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { net, safeStorage } from 'electron'
import { discoverLocalMcp, type LocalMcp } from './mcpDiscovery.ts'
import type { LocalMcpState, LocalMcpSummary } from './contracts.ts'
import { checkLocalMcpAuthentication, LocalMcpSessions, type RelayDelivery, type RelayReply } from './mcpSession.ts'

const route = '/api/services/desktop-mcp'
const desktopHeader = 'X-Desktop-MCP-Token'
const uuidPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/
const keyPattern = /^[A-Za-z0-9_-]{43}$/
const digestPattern = /^[0-9a-f]{64}$/
const maxShared = 8
const maxImports = 16
const maxMessage = 1024 * 1024
type SavedShare = { relay: string; token: string; fingerprint: string; enabled: boolean; summary: LocalMcpSummary }
type Preferences = { imported: string[]; servers: Record<string, Record<string, SavedShare>> }
type Link = { abort: AbortController; status: LocalMcpState['entries'][number]['status'] }

function isShare(value: SavedShare | undefined): value is SavedShare {
  return Boolean(value && uuidPattern.test(value.relay) && keyPattern.test(value.token)
    && digestPattern.test(value.fingerprint) && typeof value.enabled === 'boolean'
    && value.summary && digestPattern.test(value.summary.id) && typeof value.summary.name === 'string'
    && typeof value.summary.source === 'string' && ['stdio', 'http', 'sse'].includes(value.summary.transport))
}

async function post(url: string, token: string, signal: AbortSignal, data?: string, access?: string): Promise<Response> {
  const headers = new Headers({ [desktopHeader]: token })
  if (data !== undefined) headers.set('Content-Type', 'application/json')
  if (access) headers.set('Authorization', 'Bearer ' + access)
  return net.fetch(url, { method: 'POST', headers, signal, body: data, redirect: 'error', credentials: 'omit' })
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    if (signal.aborted) { resolve(); return }
    const timer = setTimeout(done, milliseconds)
    function done() {
      clearTimeout(timer)
      signal.removeEventListener('abort', done)
      resolve()
    }
    signal.addEventListener('abort', done, { once: true })
  })
}

export class DesktopMcpRelay {
  private readonly file: string
  private preferences: Preferences = { imported: [], servers: {} }
  private entries: LocalMcp[] = []
  private running = new Map<string, Link>()
  private server = ''
  private scanning = false
  private unreadable = 0
  private error: LocalMcpState['error'] = ''
  private operations: Promise<void> = Promise.resolve()
  private revoked = new Set<string>()

  constructor(directory: string, private readonly changed: (state: LocalMcpState) => void) {
    this.file = path.join(directory, 'desktop-mcp.json')
  }

  private publish(): void { this.changed(this.snapshot()) }

  async load(): Promise<void> {
    try {
      const text = await readFile(this.file, 'utf8')
      const wrapper = JSON.parse(text) as { encrypted?: string; settings?: Preferences }
      const parsed = wrapper.encrypted
        ? JSON.parse(safeStorage.decryptString(Buffer.from(wrapper.encrypted, 'base64'))) as Preferences
        : wrapper.settings
      if (parsed && Array.isArray(parsed.imported) && parsed.servers && typeof parsed.servers === 'object') {
        this.preferences = { imported: parsed.imported.filter(item => typeof item === 'string' && path.isAbsolute(item)).slice(0, maxImports),
          servers: parsed.servers }
        for (const shares of Object.values(parsed.servers)) {
          for (const share of Object.values(shares ?? {})) {
            // A share created with a tool selection needs explicit activation to share the whole MCP.
            if (isShare(share) && 'tools' in share) {
              share.enabled = false
              delete share.tools
            }
          }
        }
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') this.error = 'mcpSaveError'
    }
    await this.scan()
  }

  private async save(): Promise<void> {
    const encrypted = safeStorage.isEncryptionAvailable()
      && (process.platform !== 'linux' || safeStorage.getSelectedStorageBackend() !== 'basic_text')
    const wrapper = encrypted
      ? { encrypted: safeStorage.encryptString(JSON.stringify(this.preferences)).toString('base64') }
      : { settings: this.preferences }
    const temporary = this.file + '.tmp'
    await writeFile(temporary, JSON.stringify(wrapper), { mode: 0o600 })
    await rename(temporary, this.file)
  }

  private async serial(action: () => Promise<void>): Promise<void> {
    const task = this.operations.then(action)
    this.operations = task.catch(() => {})
    await task
  }

  private share(id: string): SavedShare | undefined {
    const value = this.preferences.servers[this.server]?.[id]
    return isShare(value) ? value : undefined
  }

  snapshot(): LocalMcpState {
    const entries: LocalMcpState['entries'] = this.entries.map(entry => {
      const share = this.share(entry.summary.id)
      const changed = Boolean(share?.enabled && share.fingerprint !== entry.fingerprint)
      return { ...entry.summary, shared: Boolean(share?.enabled),
        status: changed ? 'mcpChanged' : this.revoked.has(entry.summary.id) ? 'mcpRevoked'
          : this.running.get(entry.summary.id)?.status ?? 'mcpPrivate' }
    })
    const found = new Set(entries.map(entry => entry.id))
    for (const [id, saved] of Object.entries(this.preferences.servers[this.server] ?? {})) {
      if (isShare(saved) && saved.enabled && !found.has(id)) entries.push({ ...saved.summary, shared: true, status: 'mcpMissing' })
    }
    return { server: this.server, scanning: this.scanning, unreadable: this.unreadable, error: this.error, entries }
  }

  activate(server: string): void {
    if (this.server === server) return
    this.stop()
    this.server = server
    this.error = ''
    this.revoked.clear()
    this.syncLinks()
  }

  stop(): void {
    for (const id of this.running.keys()) void this.stopLink(id, this.share(id))
  }

  private async stopLink(id: string, saved: SavedShare | undefined): Promise<void> {
    const link = this.running.get(id)
    if (!link) return
    this.running.delete(id)
    link.abort.abort()
    if (saved && this.server) {
      await post(this.server + route + '/' + saved.relay + '/poll?offline=true', saved.token, AbortSignal.timeout(3000))
        .then(response => response.body?.cancel()).catch(() => {})
    }
  }

  private async scan(): Promise<void> {
    this.scanning = true
    this.publish()
    try {
      const { entries, unreadable } = await discoverLocalMcp(this.preferences.imported)
      for (const [id] of this.running) {
        if (!entries.some(entry => entry.summary.id === id && entry.fingerprint === this.share(id)?.fingerprint)) {
          void this.stopLink(id, this.share(id))
        }
      }
      this.entries = entries
      this.unreadable = unreadable
      this.syncLinks()
    } finally {
      this.scanning = false
      this.publish()
    }
  }

  async discover(): Promise<void> { await this.serial(() => this.scan()) }

  async importFile(file: string): Promise<void> {
    await this.serial(async () => {
      if (!this.preferences.imported.includes(file)) {
        if (this.preferences.imported.length >= maxImports) { this.error = 'mcpLimit'; this.publish(); return }
        this.preferences.imported.push(file)
        try { await this.save() } catch { this.preferences.imported.pop(); this.error = 'mcpSaveError'; this.publish(); return }
      }
      await this.scan()
    })
  }

  async setSharing(id: string, enabled: boolean, getAccess: (origin: string) => Promise<string | null>): Promise<void> {
    const server = this.server
    await this.serial(async () => {
      if (!server || this.server !== server || !digestPattern.test(id)) return
      this.error = ''
      const entry = this.entries.find(item => item.summary.id === id)
      const saved = this.share(id)
      const settings = this.preferences.servers[server] ??= {}
      if (!enabled) {
        const stopped = this.stopLink(id, saved)
        if (saved) {
          saved.enabled = false
          try { await this.save() } catch { this.error = 'mcpSaveError' }
        }
        this.revoked.delete(id)
        this.publish()
        await stopped
        return
      }
      if (!entry) return
      if (!saved?.enabled && Object.values(settings).filter(value => value?.enabled).length >= maxShared) {
        this.error = 'mcpLimit'; this.publish(); return
      }
      const access = await getAccess(server)
      if (this.server !== server) return
      if (!access) { this.error = 'mcpSignIn'; this.publish(); return }
      const rejection = await checkLocalMcpAuthentication(entry.options)
      if (this.server !== server) return
      if (rejection) {
        this.error = rejection === 401 ? 'mcpLocalAuthRequired' : 'mcpLocalAccessDenied'
        this.publish()
        return
      }
      const share = saved ?? { relay: randomUUID(), token: randomBytes(32).toString('base64url'),
        fingerprint: entry.fingerprint, enabled: false, summary: entry.summary }
      settings[id] = share
      try { await this.save() } catch { this.error = 'mcpSaveError'; this.publish(); return }
      try {
        const data = JSON.stringify({ relay: share.relay, label: entry.summary.name })
        const response = await post(server + route, share.token, AbortSignal.timeout(10000), data, access)
        await response.body?.cancel()
        if (this.server !== server) return
        if (!response.ok) {
          this.error = response.status === 401 ? 'mcpSignIn' : response.status === 403 ? 'mcpPermission' : 'mcpServerError'
          this.publish()
          return
        }
      } catch {
        if (this.server === server) { this.error = 'mcpServerError'; this.publish() }
        return
      }
      share.fingerprint = entry.fingerprint
      share.summary = entry.summary
      share.enabled = true
      try { await this.save() } catch { share.enabled = false; this.error = 'mcpSaveError'; this.publish(); return }
      if (this.server !== server) return
      this.revoked.delete(id)
      this.syncLinks()
    })
  }

  private syncLinks(): void {
    for (const entry of this.entries) {
      const id = entry.summary.id
      const saved = this.share(id)
      if (!this.server || !saved?.enabled || saved.fingerprint !== entry.fingerprint
        || this.running.has(id) || this.revoked.has(id)) continue
      const link = { abort: new AbortController(), status: 'mcpConnecting' } as Link
      this.running.set(id, link)
      void this.run(entry, saved, link, this.server + route + '/' + saved.relay)
    }
    this.publish()
  }

  private async run(entry: LocalMcp, saved: SavedShare, link: Link, url: string): Promise<void> {
    const signal = link.abort.signal
    const sessions = new LocalMcpSessions(entry.options, signal)
    const active = new Set<Promise<void>>()
    let failures = 0
    const update = (status: Link['status']) => {
      if (!signal.aborted && link.status !== status) { link.status = status; this.publish() }
    }
    while (!signal.aborted) {
      if (active.size >= 4) await Promise.race(active)
      if (signal.aborted) break
      try {
        const response = await post(url + '/poll', saved.token, AbortSignal.any([signal, AbortSignal.timeout(12000)]))
        if (signal.aborted) { await response.body?.cancel(); break }
        if (response.status === 403 || response.status === 404) {
          await response.body?.cancel()
          if (signal.aborted) break
          this.running.delete(entry.summary.id)
          this.revoked.add(entry.summary.id)
          link.abort.abort()
          this.publish()
          break
        }
        if (!response.ok) { await response.body?.cancel(); throw new Error('Polling failed') }
        const delivery = await response.json() as RelayDelivery | null
        failures = 0
        update('mcpOnline')
        if (delivery && uuidPattern.test(delivery.request) && uuidPattern.test(delivery.session) && !signal.aborted) {
          const task = sessions.handle(delivery).then(reply => this.reply(url, saved.token, delivery.request, reply, signal))
            .catch(() => {}).finally(() => active.delete(task))
          active.add(task)
        }
      } catch {
        failures++
        update('mcpOffline')
        await delay(Math.min(15_000, 1000 * 2 ** Math.min(4, failures)), signal)
      }
    }
  }

  private async reply(url: string, token: string, request: string, response: RelayReply, signal: AbortSignal): Promise<void> {
    if (signal.aborted) return
    let data = JSON.stringify({ request, response })
    if (Buffer.byteLength(data) > maxMessage) data = JSON.stringify({ request, response: { error: { code: -32000, message: 'MCP response is too large' } } })
    const result = await post(url + '/complete', token, AbortSignal.any([signal, AbortSignal.timeout(4000)]), data)
    await result.body?.cancel()
  }
}
