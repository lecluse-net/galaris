import { model3dFormat } from './model3d.ts'
import { resourceTextLanguage, resourceSourceLanguage } from './resourceText.ts'

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
  if (normalized === 'text/rtf' || /\.(doc|docx|odt|rtf|odg|odp|ppt|pptx|xls|xlsx|ods)$/.test(filename)) return null
  if (resourceSourceLanguage(name, mediaType)) return 'text'
  if (model3dFormat(normalized, filename)) return 'model3d'
  if (normalized.startsWith('image/') || filename.endsWith('.svg')) return 'image'
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
  if (browserResourceKind(mediaType, name) === 'text') {
    return URL.createObjectURL(new Blob([blob], { type: 'text/plain;charset=utf-8' }))
  }
  const htmlMediaTypes = ['text/html', 'application/xhtml+xml']
  if (!htmlMediaTypes.includes(normalizedMediaType(blob.type))
      && !htmlMediaTypes.includes(normalizedMediaType(mediaType))
      && browserResourceKind(blob.type || mediaType, name) !== 'html') {
    return URL.createObjectURL(blob)
  }
  // A file format renderer is shared by every attachment surface. Only the
  // authenticated source bytes enter it: there is no server copy or access ticket.
  // Keep untrusted HTML out of this outer document, including closing script tags.
  const payload = JSON.stringify({ content: await blob.text(), name }).replace(/</g, '\\u003c')
  const renderer = new URL('/resource-viewer.js', window.location.origin).href
  const isolated = new Blob([
    '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
    '<meta name="referrer" content="no-referrer"><style>html,body,iframe{margin:0;border:0;width:100%;height:100%;display:block}body{overflow:hidden}</style>',
    `</head><body><script type="application/json" id="resource-payload">${payload}</script>`,
    `<script src="${renderer}"></script></body></html>`,
  ], { type: 'text/html;charset=utf-8' })
  return URL.createObjectURL(isolated)
}

export function saveBlobAsResource(blob: Blob, name: string): void {
  // Browsers may append a MIME-derived extension to names such as Dockerfile.
  // A source download is opaque bytes with its authored name, never a document.
  const source = resourceSourceLanguage(name, blob.type)
    ? new Blob([blob], { type: 'application/octet-stream' }) : blob
  const url = URL.createObjectURL(source)
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
