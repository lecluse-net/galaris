import { resolveDocumentReferenceImage, sanitizeRichHtml } from '@/core/util'
import { normalizedTagIcon, preparePortableDocumentSnapshot, printStaticDocument, unicodeIcon, withAttachmentInventory, type DocumentResource } from '@/core/util/facade'
import branchCss from './branch.css?inline'
import graphicCss from './graphic.css?inline'
import { mindMapLinkHtml, mindMapParagraphHtml, mindMapResourceBody } from './content'
import { nodesByParent, type MindMap, type MindMapNode } from './model'

type Graphic = { document: Document; chart: HTMLElement }

/** Render the stored tree independently of the editor's viewport and transient selection. */
export async function prepareMindMapGraphic(
  map: MindMap,
  title: string,
  appearance: { background: string; dark: boolean; theme: Record<string, string | undefined> },
  signal: AbortSignal,
  agentId: number | null,
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>,
  archive?: { attachments: DocumentResource[]; heading: string },
): Promise<Graphic> {
  const bodies = map.nodes.map(node => mindMapResourceBody(node.body_html ?? ''))
  // Isolate raw HTML within its node before preparing the combined snapshot.
  // A marker preserves empty nodes through the editorial empty-content check.
  const markup = map.nodes.map((node, index) => {
    const note = node.note ? mindMapParagraphHtml(node.note) : ''
    const link = node.link ? mindMapLinkHtml(node.link) : ''
    return `<blockquote><span>&#8203;</span>${note}${link}${sanitizeRichHtml(bodies[index]!.html, 'document')}</blockquote>`
  }).join('')
  const content = archive ? withAttachmentInventory(markup, archive.attachments, archive.heading) : markup
  const html = await preparePortableDocumentSnapshot(content, title, signal, resolveImage, undefined,
    (uri, pending, full) => resolveDocumentReferenceImage(uri, agentId, pending, full).catch(() => null), Boolean(archive))
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const contents = [...doc.querySelectorAll('main > blockquote')]
  if (contents.length !== map.nodes.length) throw new Error('Invalid mind map content')
  const indexById = new Map(map.nodes.map((node, index) => [node.id, index]))
  const children = nodesByParent(map.nodes)
  const chart = doc.createElement('div')
  chart.className = appearance.dark ? 'mindmap-graphic body--dark' : 'mindmap-graphic'
  chart.style.backgroundColor = appearance.background
  for (const [name, value] of Object.entries(appearance.theme)) if (value) chart.style.setProperty(name, value)
  const root = doc.createElement('ul')
  root.className = 'mindmap-graphic-root'
  chart.append(root)

  function branch(node: MindMapNode, level: number): HTMLElement {
    const index = indexById.get(node.id)!
    const body = bodies[index]!
    const item = doc.createElement('li')
    item.className = 'mindmap-branch'
    item.dataset.level = String(Math.min(level, 3))
    const box = doc.createElement('div')
    box.className = 'mindmap-node'
    if (body.linkOnly && !node.note && !node.link) box.classList.add('mindmap-link-node')
    const content = contents[index]!
    content.firstElementChild?.remove()
    if (node.note) content.firstElementChild?.classList.add('mindmap-note')
    if (body.resourceOnly && !node.note && !node.link && node.checked == null && node.value == null) {
      box.classList.add(body.standaloneCard || body.embeddedFrame ? 'mindmap-card-node' : 'mindmap-resource-only')
      if (body.imageOnly) box.classList.add('mindmap-image-node')
      if (body.embeddedFrame?.borderColor) box.style.setProperty('--map-resource-border', body.embeddedFrame.borderColor)
    }
    if (!node.body_html || node.checked != null || node.value != null) {
      const label = doc.createElement('p')
      label.className = 'mindmap-label'
      if (node.checked != null) label.append(node.checked ? '☑ ' : '☐ ')
      if (!node.body_html || node.value != null) {
        const icon = normalizedTagIcon(node.icon)
        if (/^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(icon)) {
          const image = doc.createElement('img')
          image.src = icon
          image.alt = ''
          label.append(image)
        } else {
          const glyph = unicodeIcon(icon)
          if (glyph) label.append(glyph + ' ')
        }
        label.append(node.title)
      }
      if (node.value) label.append(' ' + node.value)
      box.append(label)
    }
    if (content.hasChildNodes()) {
      const rich = doc.createElement('div')
      rich.className = 'rich-content'
      rich.append(...content.childNodes)
      box.append(rich)
    }
    item.append(box)
    const descendants = children.get(node.id)
    if (descendants?.length) {
      const group = doc.createElement('ul')
      group.className = 'mindmap-children'
      group.append(...descendants.map(child => branch(child, level + 1)))
      item.append(group)
    }
    return item
  }

  root.append(branch(children.get(null)![0]!, 0))
  const inventory = [...doc.querySelectorAll('main > :is(h2, ul)')]
  doc.body.replaceChildren(chart)
  if (inventory.length) {
    const section = doc.createElement('section')
    section.className = 'rich-content'
    section.append(...inventory)
    doc.body.append(section)
  }
  const style = doc.createElement('style')
  style.textContent = branchCss + graphicCss
  doc.head.append(style)
  return { document: doc, chart }
}

export function graphicHtml(doc: Document): string { return '<!doctype html>' + doc.documentElement.outerHTML }

async function measureGraphic(doc: Document, signal: AbortSignal): Promise<{ width: number; height: number }> {
  const frame = document.createElement('iframe')
  frame.sandbox.add('allow-same-origin')
  frame.setAttribute('aria-hidden', 'true')
  frame.tabIndex = -1
  frame.style.cssText = 'position:fixed;left:-10000px;top:0;width:1200px;height:800px;border:0;pointer-events:none'
  frame.srcdoc = graphicHtml(doc)
  const pending = AbortSignal.any([signal, AbortSignal.timeout(15_000)])
  let abort: (() => void) | undefined
  try {
    pending.throwIfAborted()
    await new Promise<void>((resolve, reject) => {
      abort = () => reject(pending.reason)
      pending.addEventListener('abort', abort, { once: true })
      frame.onload = () => resolve()
      document.body.append(frame)
    })
    pending.throwIfAborted()
    const layout = frame.contentDocument?.querySelector<HTMLElement>('.mindmap-graphic')
    if (!layout) throw new Error('Map layout unavailable')
    const rect = layout.getBoundingClientRect()
    return { width: Math.ceil(rect.width), height: Math.ceil(rect.height) }
  } finally {
    if (abort) pending.removeEventListener('abort', abort)
    frame.remove()
  }
}

export async function mindMapPng({ document: doc, chart }: Graphic, signal: AbortSignal): Promise<Blob> {
  const { width, height } = await measureGraphic(doc, signal)
  signal.throwIfAborted()
  const pixelScale = Math.min(2, 8192 / Math.max(width, height), Math.sqrt(24_000_000 / (width * height)))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.floor(width * pixelScale))
  canvas.height = Math.max(1, Math.floor(height * pixelScale))
  const surface = canvas.getContext('2d')
  if (!surface) throw new Error('Map canvas unavailable')
  const wrapper = doc.createElement('div')
  wrapper.append(...[...doc.head.querySelectorAll('style')].map(style => style.cloneNode(true)), chart.cloneNode(true))
  const markup = new XMLSerializer().serializeToString(wrapper)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${canvas.width}" height="${canvas.height}" viewBox="0 0 ${width} ${height}"><foreignObject width="${width}" height="${height}">${markup}</foreignObject></svg>`
  const image = new Image()
  image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
  await image.decode()
  signal.throwIfAborted()
  surface.drawImage(image, 0, 0)
  return new Promise((resolve, reject) => canvas.toBlob(blob => {
    if (signal.aborted) reject(signal.reason)
    else if (blob) resolve(blob)
    else reject(new Error('Map image unavailable'))
  }, 'image/png'))
}

export async function printMindMap({ document: doc, chart }: Graphic, title: string, signal: AbortSignal): Promise<void> {
  const { width, height } = await measureGraphic(doc, signal)
  const style = doc.createElement('style')
  style.textContent = '@page { size: A4 landscape; margin: 10mm; }'
  doc.head.append(style)
  // Leave space for rounding inside A4 minus the 10 mm margins.
  const scale = Math.min(1, 1046 / width, 717 / height)
  const sheet = doc.createElement('div')
  sheet.style.cssText = `width:${Math.ceil(width * scale)}px;height:${Math.ceil(height * scale)}px;overflow:hidden`
  chart.style.transformOrigin = 'top left'
  chart.style.transform = `scale(${scale})`
  doc.body.replaceChildren(sheet)
  sheet.append(chart)
  await printStaticDocument(title, signal, async () => graphicHtml(doc))
}
