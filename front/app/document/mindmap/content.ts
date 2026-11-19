import { attachmentReference, canonicalRichLink, documentResourceHtml, richLinkTarget, validRichLink } from '@/core/util'
import { documentUriFromLink, providerImageReference, referenceMode, referenceUri, validReferenceAttribute } from '@/core/util/facade'

import { nodesByParent, parseMindMap, type MindMap, type MindMapNode } from './model'

function escapeHtml(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

export function mindMapParagraphHtml(value: string): string {
  return `<p>${escapeHtml(value).replace(/\r\n?|\n/g, '<br>')}</p>`
}

const rasterTypes: Record<string, string> = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif' }

export function mindMapResourceBody(html: string): {
  html: string; resourceOnly: boolean; imageOnly: boolean; linkOnly: boolean; standaloneCard: boolean
  embeddedFrame: { kind: 'document' | 'process'; borderColor?: string } | null
} {
  if (!html.includes('<a') && !html.includes('<img')) return { html, resourceOnly: false, imageOnly: false, linkOnly: false, standaloneCard: false, embeddedFrame: null }
  const body = new DOMParser().parseFromString(html, 'text/html').body
  let changed = false
  for (const paragraph of body.querySelectorAll('p')) {
    if (paragraph.parentElement !== body || paragraph.childElementCount !== 1) continue
    const link = paragraph.querySelector('a[href]'), name = link?.textContent?.trim() ?? ''
    const mediaType = rasterTypes[name.split('.').at(-1)?.toLowerCase() ?? '']
    const uri = link?.getAttribute('href') ?? ''
    if (!link || link.hasAttribute('data-resource-mode') || !mediaType || paragraph.textContent?.trim() !== name) continue
    if (attachmentReference(uri)) {
      paragraph.outerHTML = documentResourceHtml({ uri, name, mediaType, size: 0 })
    } else if (providerImageReference(uri)) {
      const card = body.ownerDocument.createElement('blockquote')
      card.className = 'galaris-link-card image'
      paragraph.replaceWith(card)
      card.append(paragraph)
    } else continue
    changed = true
  }
  const block = body.childElementCount === 1 ? body.firstElementChild : null
  const inline = block?.matches('p') && block.childElementCount === 1 && block.textContent?.trim() === block.firstElementChild?.textContent?.trim()
    ? block.firstElementChild : null
  const item = inline ?? block
  const linkOnly = Boolean(item?.matches('a[href]') && !item.querySelector('img') && body.textContent?.trim() === item.textContent?.trim())
  const resourceOnly = !linkOnly && Boolean(block?.matches('figure.image, img, blockquote.galaris-link-card')
    || item?.matches('a[href]') && item.querySelector('img')
    || inline?.matches('img, span.image-inline'))
  const card = resourceOnly && block?.matches('blockquote.galaris-link-card:not(.image)') ? block : null
  const imageOnly = resourceOnly && Boolean(block?.matches('img, blockquote.galaris-link-card.image')
    || block?.matches('figure.image, p, a[href]') && block.querySelector('img'))
  const mode = referenceMode(card)
  const target = mode === 'embed' ? richLinkTarget(referenceUri(card))?.kind : undefined
  const kind = target === 'process_run' ? 'process' : target
  const border = card?.getAttribute('data-resource-border')
  const embeddedFrame = kind === 'document' || kind === 'process'
    ? { kind, borderColor: card && border && validReferenceAttribute(card, 'data-resource-border', border) ? border : undefined } as const
    : null
  return { html: changed ? body.innerHTML : html, resourceOnly, imageOnly, linkOnly, standaloneCard: mode === 'card', embeddedFrame }
}

export function mindMapLinkHtml(value: string): string {
  const label = value.trim()
  const url = /^www\./i.test(label) ? `https://${label}` : label
  return `<p><a href="${escapeHtml(url).replaceAll('"', '&quot;')}">${escapeHtml(label)}</a></p>`
}

interface DroppedReference { uri: string; name: string }

export function mindMapReferenceUri(value: string): string | null {
  const text = value.trim()
  const href = /^www\./i.test(text) ? `https://${text}` : text
  const uri = documentUriFromLink(href, window.location.origin) ?? canonicalRichLink(href) ?? href
  return validRichLink(uri) ? uri : null
}

export function mindMapDroppedResources(data: DataTransfer): { links: DroppedReference[]; images: DroppedReference[] } {
  const template = document.createElement('template')
  template.innerHTML = data.getData('text/html')
  const links = new Map<string, DroppedReference>()
  function addLink(value: string, name = ''): void {
    const uri = mindMapReferenceUri(value)
    if (uri && !links.has(uri)) links.set(uri, { uri, name: name.trim() || uri })
  }
  for (const link of template.content.querySelectorAll('a[href]')) addLink(link.getAttribute('href')!, link.textContent ?? '')
  const plain = data.getData('text/uri-list') || data.getData('text/plain')
  for (const line of plain.split(/\r?\n/)) if (!line.startsWith('#')) addLink(line)
  const images = new Map<string, DroppedReference>()
  for (const image of template.content.querySelectorAll('img[src]')) {
    const uri = image.getAttribute('src')!
    if (!uri.startsWith('https://') || !validRichLink(uri) || images.has(uri)) continue
    const name = image.getAttribute('alt')?.trim() || new URL(uri).pathname.split('/').at(-1) || uri
    images.set(uri, { uri, name })
  }
  return { links: [...links.values()], images: [...images.values()] }
}

export function mindMapOutline(map: MindMap): string {
  const children = nodesByParent(map.nodes)
  function branch(node: MindMapNode): string {
    const note = node.note ? mindMapParagraphHtml(node.note) : ''
    const link = node.link ? mindMapLinkHtml(node.link) : ''
    const branches = children.get(node.id) ?? []
    const checkbox = node.checked == null ? '' : node.checked ? '☑ ' : '☐ '
    return `<li><p><strong>${checkbox}${escapeHtml(node.title)}</strong></p>${note}${link}${node.body_html ?? ''}${branches.length ? list(branches) : ''}</li>`
  }
  function list(nodes: MindMapNode[]): string { return `<ul>${nodes.map(branch).join('')}</ul>` }
  return list(children.get(null) ?? [])
}

export async function mindMapSnapshot(source: string, title: string, signal: AbortSignal,
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>): Promise<string> {
  const map = parseMindMap(source)
  if (!map) throw new Error('Invalid mind map')
  const { preparePortableDocumentSnapshot } = await import('@/core/util/facade')
  return preparePortableDocumentSnapshot(mindMapOutline(map), title, signal, resolveImage)
}
