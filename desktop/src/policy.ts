import { createHash } from 'node:crypto'

/** Galaris is served at the origin root, like the existing PWA and /api proxy. */
export function serverOrigin(input: unknown, development = false): string {
  if (typeof input !== 'string' || input.length > 2048) throw new Error('invalidServer')
  const url = new URL(input.trim())
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if (url.protocol !== 'https:' && !(development && loopback && url.protocol === 'http:')) throw new Error('invalidServer')
  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('invalidServer')
  return url.origin
}

export function sameOrigin(url: string, origin: string): boolean {
  try { return new URL(url).origin === origin } catch { return false }
}

export function partitionFor(origin: string): string {
  return `persist:galaris-${createHash('sha256').update(origin).digest('hex')}`
}

export function externalURL(input: string): string | null {
  try {
    const url = new URL(input)
    if (url.username || url.password) return null
    return ['https:', 'http:', 'mailto:'].includes(url.protocol) ? url.href : null
  } catch { return null }
}

export const remotePreferences = Object.freeze({
  nodeIntegration: false,
  contextIsolation: true,
  sandbox: true,
  webSecurity: true,
  allowRunningInsecureContent: false,
  webviewTag: false
})
