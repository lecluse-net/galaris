import { attachmentReference } from './richText'
import { browserResourceKind } from './resourceViewer'
import { youtubeEmbedUrl, youtubePlayer } from './youtubePlayer'

export interface DocumentPlayer { kind: 'youtube' | 'video' | 'audio' | 'pdf'; src: string; title: string }
export type DocumentMediaResolver = (documentId: string, attachmentId: string) => Promise<Blob> | undefined
export interface PdfPreviewSource { blob: Blob; title: string }

export function documentPlayer(uri: string, title: string, classes: string[] = [], mediaType = ''): DocumentPlayer | null {
  const youtube = youtubeEmbedUrl(uri)
  if (youtube) return { kind: 'youtube', src: youtube, title }
  if (!attachmentReference(uri)) return null
  const kind = classes.includes('galaris-media-video') ? 'video'
    : classes.includes('galaris-media-audio') ? 'audio'
    : classes.includes('galaris-media-pdf') ? 'pdf' : browserResourceKind(mediaType, title)
  return kind === 'video' || kind === 'audio' || kind === 'pdf' ? { kind, src: uri, title } : null
}

/** Same native controls and authenticated attachment download as the attachment viewer. */
export function createDocumentPlayer(document: Document, target: DocumentPlayer, resolve: DocumentMediaResolver, translate: (key: string) => string, openPdf: (source: PdfPreviewSource) => void): { element: HTMLElement; dispose: () => void } {
  const element = document.createElement('div')
  element.className = target.kind === 'youtube' ? 'galaris-youtube-player' : 'galaris-media-player'
  if (target.kind === 'youtube') {
    element.append(youtubePlayer(document, target.src, target.title))
    return { element, dispose: () => element.remove() }
  }
  const media = document.createElement(target.kind === 'pdf' ? 'iframe' : target.kind)
  if (media instanceof HTMLMediaElement) {
    media.controls = true
    media.preload = 'metadata'
  } else {
    media.title = target.title
    media.className = 'galaris-pdf-player'
  }
  media.setAttribute('aria-label', target.title)
  if (media instanceof HTMLVideoElement) media.playsInline = true
  const frame = document.createElement('div')
  if (target.kind === 'pdf') {
    frame.className = 'galaris-pdf-frame'
    frame.append(media)
    element.append(frame)
  } else element.append(media)
  const expand = document.createElement('button')
  if (target.kind === 'pdf') {
    expand.type = 'button'
    expand.className = 'galaris-pdf-expand'
    expand.title = translate('richEditor.resources.openPdf')
    expand.setAttribute('aria-label', expand.title)
    expand.disabled = true
    const icon = document.createElement('span')
    icon.className = 'material-icons'
    icon.setAttribute('aria-hidden', 'true')
    icon.textContent = 'open_in_full'
    expand.append(icon)
    element.append(expand)
  }
  let disposed = false, objectUrl: string | undefined
  const error = document.createElement('button')
  error.type = 'button'
  error.className = 'galaris-media-retry'
  error.textContent = translate('richEditor.resources.retryMedia')
  const load = async (): Promise<void> => {
    error.remove()
    element.setAttribute('aria-busy', 'true')
    try {
      const reference = attachmentReference(target.src)
      const blob = reference && await resolve(...reference)
      if (disposed) return
      if (!blob) throw new Error('Attachment unavailable')
      objectUrl = URL.createObjectURL(blob)
      media.src = objectUrl + (target.kind === 'pdf' ? '#view=FitH' : '')
      if (target.kind === 'pdf') {
        expand.disabled = false
        expand.onclick = () => openPdf({ blob, title: target.title })
      }
    } catch {
      if (!disposed) element.append(error)
    } finally { element.removeAttribute('aria-busy') }
  }
  error.onclick = () => { void load() }
  void load()
  return { element, dispose: () => {
    disposed = true
    if (media instanceof HTMLMediaElement) media.pause()
    media.removeAttribute('src')
    if (media instanceof HTMLMediaElement) media.load()
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    element.remove()
  } }
}
