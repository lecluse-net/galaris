import { documentIdFromResourceUri } from './documentResource'

export function resourceCardUri(card: HTMLElement): string {
  const link = card.querySelector('a')
  return link?.getAttribute('data-rich-reference') ?? link?.getAttribute('href') ?? ''
}

export function embeddedResourceCards(root: ParentNode): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>('blockquote.galaris-link-card')].filter(card =>
    card.matches('.galaris-process-diagram, .galaris-agent-card') || documentIdFromResourceUri(resourceCardUri(card)))
}

/** Rendering-only decoration also upgrades existing document cards without rewriting them. */
export function prepareDocumentCard(card: HTMLElement, interactive = true): void {
  const id = documentIdFromResourceUri(resourceCardUri(card))
  if (!id) return
  card.classList.add('galaris-document-card')
  let identifier = [...card.querySelectorAll('p')].find(paragraph => paragraph.textContent === id)
  if (!identifier) { identifier = card.ownerDocument.createElement('p'); identifier.textContent = id; card.append(identifier) }
  identifier.hidden = interactive
}
