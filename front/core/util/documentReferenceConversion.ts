import { attachmentReference } from './documentResource'
import { documentResourceHtml, type DocumentResource } from './documentResources'
import { referenceAttributes, referenceMode, referenceUri, resourceBlock, resourceLinkElement, type DocumentReferenceMode } from './documentReference'
import { sanitizeRichHtml } from './richText'

export const editableImageType = /^image\/(png|jpeg|webp|gif)$/

export function parseReferenceElement(html: string): HTMLElement | null {
  const parsed = document.createElement('template')
  parsed.innerHTML = html
  return parsed.content.firstElementChild as HTMLElement | null
}

function referenceSource(source: HTMLElement): string {
  const copy = source.cloneNode(true) as HTMLElement
  for (const element of [copy, ...copy.querySelectorAll(referenceAttributes.map(attribute => `[${attribute}]`).join(','))]) {
    for (const attribute of referenceAttributes) element.removeAttribute(attribute)
  }
  const html = copy.outerHTML
  if (html.length > 32_768) throw new Error('Reference presentation is too large')
  return html
}

function restoreSource(source: string | undefined, selector: string, uri: string): HTMLElement | null {
  if (!source || /\bdata-resource-(?:mode|border|shadow|size|image|card)\s*=/i.test(source)) return null
  const element = parseReferenceElement(sanitizeRichHtml(source, 'document'))
  return element?.matches(selector) && referenceUri(element) === uri ? element : null
}

interface ReferenceConversion {
  uri: string
  title: string
  origin: HTMLElement | null
  attachment?: DocumentResource
  image: boolean
  providerImage?: boolean
  createCard?: () => Promise<string>
}

export async function convertDocumentReference(reference: ReferenceConversion, mode: DocumentReferenceMode): Promise<string> {
  const { origin, uri, title, attachment, image, providerImage, createCard } = reference
  const currentBlock = origin?.matches('blockquote.galaris-link-card') ? origin : null
  const currentImage = origin?.matches('figure.image, img, span.image-inline') ? origin : null
  const imageSource = currentImage ? referenceSource(currentImage) : origin?.dataset.resourceImage
  const cardSource = currentBlock && (referenceMode(currentBlock) !== 'embed' || currentBlock.matches('.image'))
    ? referenceSource(currentBlock) : origin?.dataset.resourceCard
  let result: HTMLElement | null

  if (mode === 'link') result = resourceLinkElement(uri, title)
  else if (mode === 'embed' && image && attachmentReference(uri)) {
    result = restoreSource(imageSource, 'figure.image, img, span.image-inline', uri)
      ?? parseReferenceElement(documentResourceHtml({ uri, name: title, size: 0, ...attachment, mediaType: attachment?.mediaType ?? 'image/png' }, title))
  } else {
    result = restoreSource(cardSource, 'blockquote.galaris-link-card', uri)
      ?? (currentBlock?.cloneNode(true) as HTMLElement | null)
    if (!result && createCard && mode === 'card') result = parseReferenceElement(sanitizeRichHtml(await createCard(), 'document'))
    if (!result && attachment && !image) result = parseReferenceElement(documentResourceHtml(attachment, title))
    result ??= resourceBlock(uri, title, mode)
    if (!result.matches('blockquote.galaris-link-card')) throw new Error('Invalid resource card')
    if (providerImage || image && mode === 'card') result.classList.add('image')
    // Keep a real link as the fallback when a figure was the entirety of a preview.
    const heading = result.querySelector('a[href]')
    if (!heading) result.prepend(resourceBlock(uri, title, mode).firstElementChild!)
    else if (origin?.matches('a') && title !== uri && !heading.querySelector('img')) {
      const label = heading.querySelector('strong') ?? heading
      label.textContent = title
    }
  }

  if (!result) throw new Error('Invalid resource presentation')
  for (const attribute of referenceAttributes) result.removeAttribute(attribute)
  result.dataset.resourceMode = mode
  if (imageSource && !result.matches('figure.image, img, span.image-inline')) result.dataset.resourceImage = imageSource
  if (cardSource && mode !== 'card') result.dataset.resourceCard = cardSource
  if (origin?.dataset.resourceBorder) result.dataset.resourceBorder = origin.dataset.resourceBorder
  if (origin?.dataset.resourceShadow) result.dataset.resourceShadow = origin.dataset.resourceShadow
  if (origin?.dataset.resourceSize) result.dataset.resourceSize = origin.dataset.resourceSize
  return result.outerHTML
}
