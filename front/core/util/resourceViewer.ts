import { model3dFormat } from './model3d.ts'
import { resourceTextLanguage } from './resourceText.ts'

/** Preview formats shared by chat resources and document attachments. */
export type BrowserResourceKind = 'audio' | 'html' | 'image' | 'pdf' | 'video' | 'model3d' | 'markdown' | 'text'

export interface NavigationClick {
  button: number
  altKey: boolean
  ctrlKey: boolean
  metaKey: boolean
  shiftKey: boolean
  defaultPrevented: boolean
}

export function normalizedMediaType(value: string): string {
  return value.split(';', 1)[0]?.trim().toLowerCase() ?? ''
}

export function browserResourceKind(mediaType: string, name = ''): BrowserResourceKind | null {
  const normalized = normalizedMediaType(mediaType)
  const filename = name.trim().toLowerCase()
  if (model3dFormat(normalized, filename)) return 'model3d'
  if (normalized.startsWith('image/')) return 'image'
  if (normalized === 'text/html' || normalized === 'application/xhtml+xml' || /\.x?html?$/.test(filename)) return 'html'
  if (normalized === 'application/pdf' || filename.endsWith('.pdf')) return 'pdf'
  if (normalized.startsWith('audio/')) return 'audio'
  if (normalized.startsWith('video/')) return 'video'
  if (['text/markdown', 'text/x-markdown'].includes(normalized) || /\.(md|markdown|mdown|mkd)$/.test(filename)) return 'markdown'
  if (/\.(mp3|wav|ogg|oga|m4a|aac|flac|opus)$/.test(filename)) return 'audio'
  if (/\.(mp4|webm|ogv|mov|m4v|mkv)$/.test(filename)) return 'video'
  if (resourceTextLanguage(normalized, filename) !== null) return 'text'
  return null
}

export function shouldOpenInline(event: NavigationClick): boolean {
  return !event.defaultPrevented
    && event.button === 0
    && !event.altKey
    && !event.ctrlKey
    && !event.metaKey
    && !event.shiftKey
}

export async function isolatedBrowserResourceUrl(
  blob: Blob,
  mediaType: string,
  name: string,
): Promise<string> {
  if (browserResourceKind(blob.type || mediaType, name) !== 'html') {
    return URL.createObjectURL(blob)
  }
  const isolated = new Blob(
    [await blob.arrayBuffer()],
    { type: 'text/html;charset=utf-8' },
  )
  return URL.createObjectURL(isolated)
}

export function saveBlobAsResource(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name.trim() || 'resource'
  link.rel = 'noopener'
  link.hidden = true
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}
