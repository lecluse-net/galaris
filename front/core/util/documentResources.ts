import { browserResourceKind } from './resourceViewer'
import { formatFileSize } from './fileSize'

export interface DocumentResource { uri: string; name: string; size: number; mediaType?: string }

/** Persist rich text and canonical URIs; audio/video players are added only at render time. */
export function documentResourceHtml(resource: DocumentResource, label = resource.name): string {
  const anchor = document.createElement('a')
  anchor.href = resource.uri
  if (/^image\/(png|jpeg|webp|gif)$/.test(resource.mediaType ?? '')) {
    const figure = document.createElement('figure'), image = document.createElement('img')
    figure.className = 'image'; image.src = resource.uri; image.alt = label
    anchor.append(image); figure.append(anchor)
    return figure.outerHTML
  }
  const card = document.createElement('blockquote'), title = document.createElement('p'), strong = document.createElement('strong')
  card.className = 'galaris-link-card'; strong.textContent = label; anchor.append(strong); title.append(anchor); card.append(title)
  const kind = browserResourceKind(resource.mediaType ?? '', resource.name)
  if (kind === 'video' || kind === 'audio' || kind === 'pdf') card.classList.add('galaris-media-' + kind)
  const detail = document.createElement('p')
  const extension = resource.name.split('.').at(-1)?.toUpperCase()
  detail.textContent = [extension, formatFileSize(resource.size, document.documentElement.lang || navigator.language)].filter(Boolean).join(' · ')
  card.append(detail)
  return card.outerHTML
}

/** Add a readable attachment inventory without changing the authored document. */
export function withAttachmentInventory(html: string, attachments: DocumentResource[], heading: string): string {
  if (!attachments.length) return html
  const section = document.createElement('div')
  const title = document.createElement('h2'); title.textContent = heading; section.append(title)
  const list = document.createElement('ul'); section.append(list)
  for (const attachment of attachments) {
    const item = document.createElement('li'), link = document.createElement('a')
    link.href = attachment.uri; link.textContent = attachment.name
    item.append(link, ` (${formatFileSize(attachment.size, document.documentElement.lang || navigator.language)})`); list.append(item)
  }
  return html + section.innerHTML
}
