import { documentIdFromResourceUri } from './documentResource'
import { documentFolderId } from './documentFolderResource'

export function resourceCardUri(card: HTMLElement): string {
  const link = card.querySelector('a')
  return link?.getAttribute('data-rich-reference') ?? link?.getAttribute('href') ?? ''
}

export function isEmbeddedResourceCard(card: HTMLElement): boolean {
  return card.matches('blockquote.galaris-link-card') && Boolean(
    card.matches('.galaris-process-diagram, .galaris-agent-card, .galaris-contact-card')
    || documentIdFromResourceUri(resourceCardUri(card)) || documentFolderId(resourceCardUri(card)))
}

export function embeddedResourceCards(root: ParentNode): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>('blockquote.galaris-link-card')].filter(isEmbeddedResourceCard)
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
