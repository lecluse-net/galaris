import contentCss from './editorialContent.css?inline'
import richCss from './richText.css?inline'
import printCss from './documentPrint.css?inline'
import { attachmentReference, richLinkHref, sanitizeRichHtml } from './richText'
import { highlightDocumentCode } from './codeHighlight'
import { hideInteractiveSource } from './interactiveHtml'
import { solaireStyles } from './solaire'
import { layoutDocumentRendering } from './layoutDocumentRendering'
import type { RenderedDocumentResolver } from './renderedDocument'
import { embeddedResourceCards, prepareDocumentCard } from './resourceCards'

const MAX_SNAPSHOT_BYTES = 12_000_000

/** The same print document, with embedded images for the isolated browser renderer. */
export async function preparePortableDocumentSnapshot(
  content: string,
  title: string,
  signal: AbortSignal,
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>,
  resolveRenderedContent?: RenderedDocumentResolver,
): Promise<string> {
  let imageBytes = 0
  const html = await prepareDocumentSnapshot(content, title, signal, async blob => {
    imageBytes += Math.ceil(blob.size / 3) * 4
    if (imageBytes > MAX_SNAPSHOT_BYTES) throw new Error('Document snapshot too large')
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      const abort = () => reader.abort()
      signal.addEventListener('abort', abort, { once: true })
      reader.onloadend = () => {
        signal.removeEventListener('abort', abort)
        if (signal.aborted) reject(signal.reason)
        else if (reader.error || typeof reader.result !== 'string') reject(reader.error ?? new Error('Image unavailable'))
        else resolve(reader.result)
      }
      reader.readAsDataURL(blob)
    })
  }, resolveImage, false, resolveRenderedContent)
  if (new Blob([html]).size > MAX_SNAPSHOT_BYTES) throw new Error('Document snapshot too large')
  return html
}

/** Shared static, light document snapshot for printing and PDF export. */
export async function prepareDocumentSnapshot(
  content: string,
  title: string,
  signal: AbortSignal,
  imageUrl: (blob: Blob) => Promise<string>,
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>,
  portableAttachments = false,
  resolveRenderedContent?: RenderedDocumentResolver,
): Promise<string> {
  signal.throwIfAborted()
  const doc = new DOMParser().parseFromString(sanitizeRichHtml(content, 'document'), 'text/html')
  doc.querySelectorAll('script').forEach(script => script.remove())
  const interactive = [...doc.querySelectorAll('pre > code.language-galaris-app, pre > code.language-galaris-raw-html')]
  const resources = embeddedResourceCards(doc)
  resources.forEach(card => prepareDocumentCard(card, false))
  // Capture before loading attachments so all live regions reflect this export action.
  const renderings = resolveRenderedContent ? await Promise.all(interactive.map((code, index) => resolveRenderedContent(
    code.textContent ?? '', code.classList.contains('language-galaris-app') ? 'galaris-app' : 'galaris-raw-html', index, signal,
  ))) : []
  const resourceRenderings = resolveRenderedContent ? await Promise.all(resources.map((card, index) => resolveRenderedContent(
    card.querySelector('a')?.getAttribute('href') ?? '', 'galaris-resource-card', index, signal,
  ))) : []
  if (!resolveRenderedContent) hideInteractiveSource(doc.body, title)
  highlightDocumentCode(doc.body)
  doc.querySelectorAll('a').forEach(link => {
    if (portableAttachments && attachmentReference(link.getAttribute('href') ?? '')) return
    const href = richLinkHref(link.getAttribute('href') ?? '')
    if (href) link.href = new URL(href, window.location.href).href
    else link.removeAttribute('href')
  })
  await Promise.all([...doc.querySelectorAll('img')].map(async image => {
    const reference = attachmentReference(image.getAttribute('src') ?? '')
    image.removeAttribute('src')
    if (!reference || !resolveImage) throw new Error('Document image unavailable')
    const blob = await resolveImage(...reference)
    signal.throwIfAborted()
    image.src = await imageUrl(blob)
  }))
  signal.throwIfAborted()
  await Promise.all(interactive.map(async (code, index) => {
    const html = renderings[index]
    if (html === undefined) return
    if (html.length > MAX_SNAPSHOT_BYTES) throw new Error('Document snapshot too large')
    const fragment = await layoutDocumentRendering(html, signal)
    if (!portableAttachments) fragment.querySelectorAll('a').forEach(link => { link.removeAttribute('href'); link.removeAttribute('xlink:href') })
    code.parentElement!.replaceWith(fragment)
  }))
  await Promise.all(resources.map(async (card, index) => {
    const rendering = resourceRenderings[index]
    if (rendering === undefined) return
    if (rendering.length > MAX_SNAPSHOT_BYTES) throw new Error('Document snapshot too large')
    const fragment = await layoutDocumentRendering(rendering, signal, true)
    const embed = doc.createElement('div'); embed.className = 'galaris-resource-embed'
    embed.append(fragment); card.append(embed)
  }))
  if (!portableAttachments) doc.querySelectorAll('a').forEach(link => {
    if (link.closest('.galaris-link-card') || link.querySelector('img, svg, canvas, iframe, object, embed')) link.removeAttribute('href')
  })
  signal.throwIfAborted()
  const csp = "default-src 'none'; style-src 'unsafe-inline'; img-src blob: data:; base-uri 'none'; form-action 'none'"
  const heading = document.createElement('title')
  heading.textContent = title
  const html = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}">${heading.outerHTML}<style>${solaireStyles}\n${contentCss}\n${richCss}\n${printCss}</style></head><body><main class="rich-content">${doc.body.innerHTML}</main></body></html>`
  if (new Blob([html]).size > MAX_SNAPSHOT_BYTES) throw new Error('Document snapshot too large')
  return html
}
