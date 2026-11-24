import { randomBytes } from 'node:crypto'
import { net } from 'electron'
import type { ScreenRequest } from './contracts.ts'
import { sameOrigin } from './policy.ts'

const headerName = 'X-Galaris-Chat-Desktop'
const route = '/api/chat/desktop-screen'
const chatSend = /^\/api\/chat\/rooms\/[0-9a-f-]{36}\/(?:messages|attachments)$/
const uuidPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/
const jwt = /^Bearer [A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/
const idleMs = 5 * 60_000

interface TabLink {
  origin: string
  key: string
  authorization: string
  abort: AbortController
  active: () => boolean
  expires: number
  dispose: () => void
  ready: Promise<boolean>
  prompt?: { id: string; abort: AbortController }
}

function readRequest(value: unknown): ScreenRequest | null {
  if (!value || typeof value !== 'object') return null
  const data = value as Partial<ScreenRequest>
  if (typeof data.id !== 'string' || !uuidPattern.test(data.id) || typeof data.agent !== 'string'
    || typeof data.reason !== 'string' || typeof data.expires_at !== 'string') return null
  const expires = Date.parse(data.expires_at)
  if (!Number.isFinite(expires) || expires <= Date.now() || expires > Date.now() + 60_000) return null
  return { id: data.id, agent: data.agent.slice(0, 255), reason: data.reason.slice(0, 400), expires_at: data.expires_at }
}

export class ChatScreenChannel {
  private readonly tabs = new Map<number, TabLink>()
  private readonly show: (request: ScreenRequest, signal: AbortSignal) => Promise<ArrayBuffer | null>

  constructor(show: (request: ScreenRequest, signal: AbortSignal) => Promise<ArrayBuffer | null>) {
    this.show = show
  }

  install(session: Electron.Session, origin: string, isActive: (contents: Electron.WebContents) => boolean): void {
    session.webRequest.onBeforeSendHeaders((details, callback) => {
      const headers = details.requestHeaders
      const incoming = Object.keys(headers).filter(name => name.toLowerCase() === headerName.toLowerCase())
      // Strip caller-provided values and values carried to a redirect destination.
      for (const name of incoming) delete headers[name]
      const contents = details.webContents
      if (details.method === 'POST' && sameOrigin(details.url, origin) && chatSend.test(new URL(details.url).pathname)
        && contents && !contents.isDestroyed() && details.frame === contents.mainFrame
        && sameOrigin(contents.getURL(), origin) && isActive(contents)) {
        const auth = Object.entries(headers).find(([name]) => name.toLowerCase() === 'authorization')?.[1]
        if (auth && auth.length <= 4096 && jwt.test(auth)) {
          const live = () => !contents.isDestroyed() && sameOrigin(contents.getURL(), origin) && isActive(contents)
          void this.admit(contents, origin, auth, live).then(key => {
            if (key) headers[headerName] = key
            callback({ requestHeaders: headers })
          }, () => callback({ requestHeaders: headers }))
          return
        }
      }
      callback(incoming.length ? { requestHeaders: headers } : {})
    })
  }

  private async admit(contents: Electron.WebContents, origin: string, authorization: string, active: () => boolean): Promise<string | null> {
    const existing = this.tabs.get(contents.id)
    if (existing && existing.authorization === authorization) {
      existing.prompt?.abort.abort()
      existing.expires = Date.now() + idleMs
      return await existing.ready && active() && !existing.abort.signal.aborted ? existing.key : null
    }
    if (existing) this.close(contents.id)
    const id = contents.id
    const dispose = () => this.close(id)
    const navigation = (_event: unknown, _url: string, inPlace: boolean, mainFrame: boolean) => {
      if (mainFrame && !inPlace) dispose()
    }
    contents.once('destroyed', dispose)
    contents.on('did-start-navigation', navigation)
    const link: TabLink = {
      origin, key: randomBytes(32).toString('base64url'), authorization, ready: Promise.resolve(false),
      abort: new AbortController(), active, expires: Date.now() + idleMs,
      dispose: () => {
        contents.off('destroyed', dispose)
        contents.off('did-start-navigation', navigation)
      }
    }
    this.tabs.set(id, link)
    link.ready = this.fetch(link, '/poll?initialize=true', 'POST',
      AbortSignal.any([link.abort.signal, AbortSignal.timeout(1800)])).then(async response => {
      await response.body?.cancel()
      if (!response.ok || link.abort.signal.aborted) return false
      void this.poll(id, link)
      return true
    }).catch(() => false)
    if (await link.ready) return active() && !link.abort.signal.aborted ? link.key : null
    if (this.tabs.get(id) === link) this.close(id)
    return null
  }

  stop(): void {
    for (const id of this.tabs.keys()) this.close(id)
  }

  private close(id: number): void {
    const link = this.tabs.get(id)
    if (!link) return
    this.tabs.delete(id)
    link.abort.abort()
    link.dispose()
    const signal = AbortSignal.timeout(2000)
    void this.fetch(link, '', 'DELETE', signal).then(response => response.body?.cancel()).catch(() => {})
  }

  private fetch(link: TabLink, suffix: string, method: 'POST' | 'DELETE', signal: AbortSignal,
    image?: ArrayBuffer | null): Promise<Response> {
    const headers = new Headers({ Authorization: link.authorization, [headerName]: link.key })
    if (image) headers.set('Content-Type', 'image/jpeg')
    return net.fetch(link.origin + route + suffix, { method, headers, signal, body: image ?? undefined,
      redirect: 'error', credentials: 'omit' })
  }

  private async poll(id: number, link: TabLink): Promise<void> {
    const signal = link.abort.signal
    try {
      while (!signal.aborted && Date.now() < link.expires) {
        const prompt = link.prompt
        const response = await this.fetch(link, prompt ? '/poll?active=' + prompt.id : '/poll', 'POST',
          AbortSignal.any([signal, AbortSignal.timeout(12_000)]))
        if (response.status === 410 && prompt) {
          await response.body?.cancel()
          prompt.abort.abort()
          continue
        }
        if (!response.ok || signal.aborted) {
          await response.body?.cancel()
          return
        }
        const request = readRequest(await response.json())
        if (request && !signal.aborted) {
          void this.answer(link, request).catch(() => {})
        }
      }
    } catch {
      // An interrupted link expires. The next desktop Chat message establishes a new one.
    } finally {
      if (this.tabs.get(id) === link) this.close(id)
    }
  }

  private async answer(link: TabLink, request: ScreenRequest): Promise<void> {
    const cancelled = new AbortController()
    const signal = AbortSignal.any([link.abort.signal, cancelled.signal,
      AbortSignal.timeout(Math.max(1, Date.parse(request.expires_at) - Date.now()))])
    const canPrompt = link.active() && !link.prompt && !signal.aborted
    if (canPrompt) link.prompt = { id: request.id, abort: cancelled }
    try {
      const image = canPrompt ? await this.show(request, signal) : null
      if (signal.aborted) return
      const response = await this.fetch(link, '/' + request.id + '/complete', 'POST',
        AbortSignal.any([signal, AbortSignal.timeout(5000)]), link.active() ? image : null)
      await response.body?.cancel()
    } finally {
      if (link.prompt?.abort === cancelled) link.prompt = undefined
    }
  }
}
