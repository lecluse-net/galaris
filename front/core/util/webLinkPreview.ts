import { richLinkPreviewImage, validRichLink } from './richText'

/** The saved card contains only authored text and its public source URL. */
export function webLinkCardUrl(card: Element): string | null {
  if (!card.matches('blockquote.galaris-link-card.galaris-web-card')) return null
  const link = card.querySelector('a')
  const uri = link?.getAttribute('data-rich-reference') ?? link?.getAttribute('href') ?? ''
  return uri.startsWith('https://') && validRichLink(uri) ? uri : null
}

export async function webLinkCardImage(card: Element, agentId: number | null, signal: AbortSignal): Promise<Blob | null> {
  const uri = webLinkCardUrl(card)
  if (!uri) return null
  try { return await richLinkPreviewImage(uri, agentId, signal) }
  catch { signal.throwIfAborted(); return null }
}

export function prependWebLinkImage(card: Element, src: string): HTMLImageElement {
  const figure = card.ownerDocument.createElement('figure'), image = card.ownerDocument.createElement('img')
  const link = card.ownerDocument.createElement('a')
  figure.className = 'image'
  link.href = webLinkCardUrl(card)!
  link.rel = 'noopener noreferrer'; link.target = '_blank'
  image.src = src; image.alt = card.querySelector('strong')?.textContent ?? ''; image.width = 320
  link.append(image); figure.append(link); card.prepend(figure)
  return image
}

/** Node-view decoration never enters Tiptap's saved HTML. */
export function mountWebLinkPreview(card: Element, agentId: number | null): () => void {
  const controller = new AbortController()
  let url: string | undefined
  let image: HTMLImageElement | undefined
  void webLinkCardImage(card, agentId, controller.signal).then(blob => {
    if (!blob || controller.signal.aborted) return
    url = URL.createObjectURL(blob)
    image = prependWebLinkImage(card, url)
    image.dataset.editorPreview = url
  }).catch(() => { /* An interrupted preview leaves the text card usable. */ })
  return () => { controller.abort(); image?.closest('figure')?.remove(); if (url) URL.revokeObjectURL(url) }
}
