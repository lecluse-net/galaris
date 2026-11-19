import { attachmentReference } from './documentResource'
import { documentPlayer } from './documentMedia'
import { canonicalResourceLink } from './resourceUri'

export type DocumentReferenceMode = 'link' | 'card' | 'embed'
export const referenceAttributes = [
  'data-resource-mode', 'data-resource-border', 'data-resource-shadow', 'data-resource-size', 'data-resource-image', 'data-resource-card',
] as const
export type ReferenceAttribute = typeof referenceAttributes[number]
export interface DocumentEmbedSize { width: number; height: number }
export const maxDocumentEmbedSize = 4096
export function parseDocumentEmbedSize(value: string | null | undefined): DocumentEmbedSize | undefined {
  const match = /^([1-9][0-9]{0,3})x([1-9][0-9]{0,3})$/.exec(value ?? '')
  if (!match) return
  const width = Number(match[1]), height = Number(match[2])
  if (width <= maxDocumentEmbedSize && height <= maxDocumentEmbedSize) return { width, height }
}
export function writeDocumentEmbedSize(element: HTMLElement, size: DocumentEmbedSize): void {
  element.dataset.resourceSize = `${size.width}x${size.height}`
}
export function documentReferenceCards(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>('blockquote.galaris-link-card')]
    .filter(card => !root.contains(card.closest('.galaris-resource-embed')))
}

/** Match revisions that differ only in the dimensions of reference blocks. */
export function referenceSizeChanges(before: string, after: string): Array<string | null> | null {
  if (before === after || ![before, after].some(html => html.includes('data-resource-size'))) return null
  const parser = new DOMParser()
  const previous = parser.parseFromString(before, 'text/html').body
  const next = parser.parseFromString(after, 'text/html').body
  const sizes = Array.from(next.querySelectorAll('blockquote.galaris-link-card'), card => {
    const size = card.getAttribute('data-resource-size')
    card.removeAttribute('data-resource-size')
    return parseDocumentEmbedSize(size) ? size : null
  })
  previous.querySelectorAll('blockquote.galaris-link-card[data-resource-size]').forEach(card => card.removeAttribute('data-resource-size'))
  return previous.innerHTML === next.innerHTML ? sizes : null
}
export interface DocumentReferenceAction { id: string; label: string; icon: string; run: () => void }
export type RegisterDocumentReferenceActions = (actions: readonly DocumentReferenceAction[]) => void

export function explicitReferenceMode(element?: Element | null): DocumentReferenceMode | undefined {
  const mode = element?.getAttribute('data-resource-mode')
  return mode === 'link' || mode === 'card' || mode === 'embed' ? mode : undefined
}

export function referenceMode(element?: Element | null): DocumentReferenceMode {
  return explicitReferenceMode(element) ?? (element?.matches('img, figure.image, span.image-inline, .galaris-process-diagram, .galaris-link-card.image')
    || element?.matches('blockquote.galaris-link-card') && Boolean(referencePlayer(element)) ? 'embed'
    : element?.matches('blockquote.galaris-link-card') ? 'card' : 'link')
}

export function referencePlayer(card: Element, mediaType?: string, name?: string) {
  if (explicitReferenceMode(card) === 'card') return null
  return [...card.querySelectorAll('a[href]')].map(link => documentPlayer(
    link.getAttribute('data-rich-reference') ?? link.getAttribute('href') ?? '', name ?? link.textContent ?? '', [...card.classList], mediaType,
  )).find(Boolean) ?? null
}

export function referenceUri(element?: Element | null): string {
  if (!element) return ''
  const image = element.matches('img') ? element : element.querySelector('img')
  const source = image?.getAttribute('src') ?? ''
  if (!element.matches('blockquote') && attachmentReference(source)) return source
  const link = element.matches('a') ? element : element.querySelector('a')
  return link?.getAttribute('data-rich-reference') ?? link?.getAttribute('href') ?? ''
}

/** Resolve the historical Files navigation URL for provider-backed images. */
export function providerImageReference(href: string): { uri: string; agent?: number } | null {
  if (canonicalResourceLink(href) && !/^(document|data|memory|galaris):\/\//.test(href)) return { uri: href }
  try {
    const url = new URL(href, window.location.href)
    if (url.origin !== window.location.origin || url.pathname !== '/files') return null
    const uri = url.searchParams.get('uri'), agent = Number(url.searchParams.get('agent_id'))
    return uri && canonicalResourceLink(uri) ? { uri, agent: agent > 0 && Number.isSafeInteger(agent) ? agent : undefined } : null
  } catch { return null }
}

export function resourceLinkElement(uri: string, title: string): HTMLAnchorElement {
  const link = document.createElement('a')
  link.setAttribute('href', uri)
  link.textContent = title || uri
  return link
}

export function linkIconElement(document: Document, icon: string): HTMLElement {
  const element = document.createElement('span')
  element.className = 'document-reference-link-icon material-icons'
  element.dataset.icon = icon
  element.contentEditable = 'false'
  element.setAttribute('aria-hidden', 'true')
  return element
}

export function resourceBlock(uri: string, title: string, mode: 'card' | 'embed'): HTMLQuoteElement {
  const block = document.createElement('blockquote'), paragraph = document.createElement('p')
  block.className = 'galaris-link-card'
  block.dataset.resourceMode = mode
  paragraph.append(resourceLinkElement(uri, title)); block.append(paragraph)
  return block
}

export function validReferenceAttribute(element: Element, key: ReferenceAttribute, value: string): boolean {
  const link = element.matches('a[href], a[data-rich-reference]')
  const image = element.matches('figure.image, span.image-inline, img[src]')
  const block = element.matches('blockquote.galaris-link-card')
  if (!link && !image && !block) return false
  if (key === 'data-resource-mode') return link ? value === 'link' : image ? value === 'embed' : value === 'card' || value === 'embed'
  if (key === 'data-resource-border') return /^#[a-f0-9]{6}$/i.test(value)
  if (key === 'data-resource-shadow') return value === 'true'
  if (key === 'data-resource-size') return (link || block) && Boolean(parseDocumentEmbedSize(value))
  return value.length <= 32_768 && (key === 'data-resource-image' ? /^(?:<(?:figure|span|img)\b)/i : /^<blockquote\b/i).test(value)
}

export function applyReferenceAppearance(root: ParentNode): void {
  for (const element of root.querySelectorAll<HTMLElement>('[data-resource-mode="embed"]')) decorateReferenceAppearance(element)
}

export function decorateReferenceAppearance(element: HTMLElement): void {
  if (explicitReferenceMode(element) !== 'embed') return
  const color = element.dataset.resourceBorder
  if (color && validReferenceAttribute(element, 'data-resource-border', color)) element.style.setProperty('--document-embed-border', color)
}
