import { attachmentReference } from '@/core/util/facade'
import type { DocumentApp } from './documentApps'

export type AppMediaResolver = (documentId: string, attachmentId: string, signal: AbortSignal) => Promise<Blob>
const passiveMedia = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/webm', 'video/mp4', 'video/webm', 'video/ogg'])

/** Only native attachment references go through the authenticated host; CSP stays offline. */
export async function materializeAppResources(app: DocumentApp, resolve: AppMediaResolver, signal: AbortSignal): Promise<DocumentApp> {
  const doc = new DOMParser().parseFromString('<body>' + (app.html ?? ''), 'text/html')
  const resources = new Map<string, Promise<string>>()
  let totalBytes = 0
  const load = async (uri: string, reference: [string, string]): Promise<string> => {
    const existing = resources.get(uri)
    if (existing) return existing
    if (resources.size >= 32) throw new Error('Too many application attachments')
    const pending = (async () => {
      signal.throwIfAborted()
      const blob = await resolve(...reference, signal)
      signal.throwIfAborted()
      totalBytes += Math.ceil(blob.size / 3) * 4
      if (totalBytes > 12_000_000 || !passiveMedia.has(blob.type.toLowerCase())) throw new Error('Invalid or oversized application attachment')
      return await new Promise<string>((accept, reject) => {
        const reader = new FileReader()
        const abort = () => reader.abort()
        signal.addEventListener('abort', abort, { once: true })
        reader.onloadend = () => {
          signal.removeEventListener('abort', abort)
          if (signal.aborted) reject(signal.reason)
          else if (reader.error || typeof reader.result !== 'string') reject(reader.error ?? new Error('Attachment unavailable'))
          else accept(reader.result)
        }
        reader.readAsDataURL(blob)
      })
    })()
    resources.set(uri, pending)
    return pending
  }
  await Promise.all([...doc.querySelectorAll('img[src], audio[src], video[src], source[src], video[poster]')].map(async element => {
    for (const attribute of ['src', 'poster']) {
      const uri = element.getAttribute(attribute) ?? ''
      const reference = attachmentReference(uri)
      if (reference) element.setAttribute(attribute, await load(uri, reference))
    }
  }))
  signal.throwIfAborted()
  return { ...app, html: doc.body.innerHTML }
}
