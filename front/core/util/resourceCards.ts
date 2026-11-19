import { documentIdFromResourceUri } from './documentResource'
import { documentFolderId } from './documentFolderResource'
import { explicitReferenceMode, referenceMode } from './documentReference'

export type ResourceImageResolver = (uri: string, signal: AbortSignal, full: boolean) => Promise<Blob | null>

export function isLinkedImageCard(element: Element): boolean {
  return element.matches('blockquote.galaris-link-card.image')
}

export async function renderLinkedImage(card: Element, resolve: ResourceImageResolver, signal: AbortSignal,
  imageUrl: (blob: Blob) => string | Promise<string> = blob => URL.createObjectURL(blob),
): Promise<string | undefined> {
  const link = card.querySelector('a[href]')
  if (!link) return
  const uri = link.getAttribute('data-rich-reference') ?? link.getAttribute('href') ?? ''
  const blob = await resolve(uri, signal, explicitReferenceMode(card) === 'embed')
  if (!blob?.type.startsWith('image/') || signal.aborted) return
  const url = await imageUrl(blob)
  const image = card.ownerDocument.createElement('img')
  image.alt = link.textContent?.trim() ?? ''
  image.src = url
  image.setAttribute('data-rich-reference', uri)
  if (explicitReferenceMode(card) === 'card') card.prepend(image)
  else link.replaceChildren(image)
  return url
}

export function resourceCardUri(card: HTMLElement): string {
  const link = card.querySelector('a')
  return link?.getAttribute('data-rich-reference') ?? link?.getAttribute('href') ?? ''
}

export function isEmbeddedResourceCard(card: HTMLElement): boolean {
  return card.matches('blockquote.galaris-link-card') && Boolean(
    card.matches('.galaris-process-diagram, .galaris-agent-card, .galaris-contact-card')
    || explicitReferenceMode(card) && /^galaris:\/\/process(?:es)?\//.test(resourceCardUri(card))
    || documentIdFromResourceUri(resourceCardUri(card)) || documentFolderId(resourceCardUri(card)))
}

export function embeddedResourceCards(root: ParentNode): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>('blockquote.galaris-link-card')].filter(isEmbeddedResourceCard)
}

export function resourceCardDisplay(card: HTMLElement): 'legacy' | 'card' | 'embed' {
  if (explicitReferenceMode(card)) return referenceMode(card) === 'embed' ? 'embed' : 'card'
  return card.matches('.galaris-process-diagram') ? 'embed' : 'legacy'
}

/** Rendering-only decoration also upgrades existing document cards without rewriting them. */
export function prepareDocumentCard(card: HTMLElement, interactive = true): void {
  if (documentFolderId(resourceCardUri(card))) { card.classList.add('galaris-document-card'); return }
  const id = documentIdFromResourceUri(resourceCardUri(card))
  if (!id) return
  card.classList.add('galaris-document-card')
  let identifier = [...card.querySelectorAll('p')].find(paragraph => paragraph.textContent === id)
  if (!identifier) { identifier = card.ownerDocument.createElement('p'); identifier.textContent = id; card.append(identifier) }
  identifier.hidden = interactive
}
