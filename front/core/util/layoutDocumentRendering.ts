import DOMPurify from 'dompurify'

const rasterSource = /^data:image\/(png|jpeg|gif|webp);base64,/i

/** Reflow a static copy at paper width, in a disposable frame without scripts. */
export async function layoutDocumentRendering(html: string, signal: AbortSignal): Promise<DocumentFragment> {
  signal.throwIfAborted()
  const clean = DOMPurify.sanitize(html, {
    WHOLE_DOCUMENT: true,
    RETURN_DOM: true,
    ADD_TAGS: ['style', 'canvas', 'video', 'select', 'option'],
    FORBID_TAGS: ['script', 'link', 'meta', 'base', 'iframe', 'object', 'embed', 'audio'],
    FORBID_ATTR: ['srcdoc', 'srcset', 'action', 'formaction', 'autofocus', 'contenteditable', 'autoplay'],
  })
  // DOMPurify returns an inert tree. Filter resources there, before loading any document.
  const doc = clean.ownerDocument
  if (!doc) throw new Error('Document rendering unavailable')
  doc.querySelectorAll('[src]').forEach(element => {
    if (element.localName !== 'img' || !rasterSource.test(element.getAttribute('src') ?? '')) element.removeAttribute('src')
  })
  doc.querySelectorAll('[href], [xlink\\:href]').forEach(element => {
    for (const name of ['href', 'xlink:href']) if (!element.getAttribute(name)?.startsWith('#')) element.removeAttribute(name)
  })
  const policy = doc.createElement('meta')
  policy.httpEquiv = 'Content-Security-Policy'
  policy.content = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'"
  doc.head.prepend(policy)
  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.tabIndex = -1
  frame.sandbox.add('allow-same-origin')
  // A4 minus the shared 10 mm page margins and the content's 1 px borders.
  frame.style.cssText = 'position:fixed;left:-10000px;top:0;width:calc(190mm - 2px);height:277mm;border:0;pointer-events:none'
  frame.srcdoc = '<!doctype html>' + doc.documentElement.outerHTML
  const pending = AbortSignal.any([signal, AbortSignal.timeout(10000)])
  let abort: () => void = () => {}
  try {
    return await new Promise<DocumentFragment>((resolve, reject) => {
      abort = () => reject(pending.reason)
      pending.addEventListener('abort', abort, { once: true })
      frame.onload = () => {
        void (async () => {
          const rendered = frame.contentDocument, view = frame.contentWindow
          if (!rendered || !view) throw new Error('Document layout unavailable')
          await Promise.all([...rendered.images].filter(image => image.hasAttribute('src')).map(image => image.decode()))
          await rendered.fonts.ready
          pending.throwIfAborted()
          let count = 0
          function style(source: Element, target: HTMLElement | SVGElement, pseudo?: string): void {
            const computed = view!.getComputedStyle(source, pseudo)
            for (const property of computed) target.style.setProperty(property, computed.getPropertyValue(property))
            target.style.setProperty('animation', 'none', 'important')
            target.style.setProperty('transition', 'none', 'important')
            target.style.setProperty('caret-color', 'transparent')
            target.style.setProperty('print-color-adjust', 'exact')
          }
          function pseudo(source: Element, target: Element, kind: string): void {
            const content = view!.getComputedStyle(source, kind).content
            if (!content || content === 'none' || content === 'normal') return
            const span = document.createElement('span')
            style(source, span, kind)
            try { span.textContent = JSON.parse(content) as string } catch { return }
            span.style.content = 'normal'
            if (kind === '::before') target.prepend(span)
            else target.append(span)
          }
          function copy(source: Node): Node | null {
            if (++count > 10000) throw new Error('Document rendering too large')
            if (source.nodeType === Node.TEXT_NODE) return document.importNode(source, false)
            if (source.nodeType !== Node.ELEMENT_NODE) return null
            const element = source as Element
            if (['style', 'script', 'noscript'].includes(element.localName)) return null
            const raster = element.getAttribute('data-document-raster')
            const target = raster ? document.createElement('img') : document.importNode(element, false) as HTMLElement | SVGElement
            if (raster) {
              if (!rasterSource.test(raster)) throw new Error('Invalid document raster')
              target.setAttribute('src', raster)
              target.setAttribute('alt', element.getAttribute('aria-label') ?? '')
            } else {
              for (const child of element.childNodes) { const node = copy(child); if (node) target.append(node) }
            }
            style(element, target)
            if (element.namespaceURI === 'http://www.w3.org/1999/xhtml' && !['input', 'textarea', 'select', 'img', 'canvas', 'video'].includes(element.localName)) {
              pseudo(element, target, '::before'); pseudo(element, target, '::after')
            }
            return target
          }
          const body = copy(rendered.body) as HTMLElement
          const root = document.createElement('div')
          root.style.cssText = body.style.cssText
          root.style.width = '100%'; root.style.boxSizing = 'border-box'
          root.style.height = 'auto'; root.style.minHeight = '0'; root.style.maxHeight = 'none'; root.style.overflow = 'visible'
          root.replaceChildren(...body.childNodes)
          const fragment = document.createDocumentFragment()
          fragment.append(root)
          return fragment
        })().then(resolve, reject)
      }
      document.body.append(frame)
    })
  } finally {
    pending.removeEventListener('abort', abort)
    frame.onload = null
    frame.remove()
  }
}
