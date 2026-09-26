import DOMPurify from 'dompurify'
import { attachmentReference, sanitizeRichHtml } from './richText'
import { editorialClasses, validEditorialStyle } from './editorialHtmlStyle'

const tags = 'p h1 h2 h3 h4 h5 h6 strong em u s b i del blockquote ul ol li hr a table thead tbody tfoot tr th td pre code br mark span img figure figcaption caption colgroup col sub sup div section article main header footer aside'.split(' ')
const inlineStyles = ['color', 'background-color', 'font-family', 'font-size', 'text-align', 'vertical-align', 'border', 'border-collapse']

/** Turn copied page markup into ordinary editable content, with locally owned images. */
export async function pasteDocumentHtml(html: string, options: {
  signal: AbortSignal
  upload?: (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<string>
  importImage?: (url: string, signal: AbortSignal) => Promise<string>
  imageFailed: () => void
  imageLabel: string
}): Promise<string> {
  options.signal.throwIfAborted()
  // Allow embedded image bytes before replacing them with attachment references.
  if (html.length > 20_000_000) throw new Error('Pasted HTML exceeds the import limit')
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  const base = parsed.querySelector('base[href]')?.getAttribute('href')
  const images = new Map<string, string>()
  for (const [index, image] of [...parsed.querySelectorAll('img')].entries()) {
    const source = image.getAttribute('src') ?? ''
    let resolved = source
    try { resolved = new URL(source, base || undefined).href } catch { /* Report inaccessible relative references below. */ }
    images.set(String(index), resolved)
    image.setAttribute('data-paste-image', String(index))
    image.removeAttribute('src'); image.removeAttribute('srcset')
  }
  const markup = parsed.documentElement.outerHTML
  if (markup.length > 2_000_000) throw new Error('Pasted HTML exceeds the document limit')
  // Retain selectors until the browser has resolved the page's CSS. No remote
  // resources or active markup are ever loaded into this temporary document.
  const safe = DOMPurify.sanitize(markup, {
    WHOLE_DOCUMENT: true, ALLOWED_TAGS: ['html', 'head', 'body', 'style', ...tags],
    ALLOWED_ATTR: ['style', 'class', 'id', 'href', 'title', 'alt', 'width', 'height', 'colspan', 'rowspan', 'start', 'reversed', 'data-paste-image'],
    ALLOW_DATA_ATTR: false, ADD_ATTR: ['data-paste-image'],
  })
  const frame = document.createElement('iframe')
  frame.setAttribute('sandbox', 'allow-same-origin')
  frame.setAttribute('aria-hidden', 'true')
  frame.style.cssText = 'position:fixed;left:-10000px;width:800px;height:1px;visibility:hidden;pointer-events:none'
  try {
    await new Promise<void>((resolve, reject) => {
      const abort = (): void => { cleanup(); reject(new DOMException('Aborted', 'AbortError')) }
      const timeout = window.setTimeout(abort, 10_000)
      const cleanup = (): void => { clearTimeout(timeout); options.signal.removeEventListener('abort', abort) }
      frame.onload = () => { cleanup(); resolve() }
      options.signal.addEventListener('abort', abort, { once: true })
      options.signal.throwIfAborted()
      frame.srcdoc = '<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;">' + safe
      document.body.append(frame)
    })
    options.signal.throwIfAborted()
    const doc = frame.contentDocument!, view = frame.contentWindow!
    const elements = [...doc.body.querySelectorAll<HTMLElement>('*')]
    if (elements.length > 20_000) throw new Error('Pasted HTML is too complex')
    // Snapshot first: removing a class or wrapping text must not change the
    // computed styles of later descendants while they are being imported.
    const backgrounds = new Map<Element, string>([[doc.body, view.getComputedStyle(doc.body).backgroundColor]])
    const styles = elements.map(element => {
      const computed = view.getComputedStyle(element)
      const background = ['rgba(0, 0, 0, 0)', 'transparent'].includes(computed.backgroundColor)
        ? backgrounds.get(element.parentElement!) ?? 'transparent' : computed.backgroundColor
      backgrounds.set(element, background)
      return {
        inline: inlineStyles.map(key => [key, key === 'background-color' ? background : computed.getPropertyValue(key)] as const),
        bold: Number(computed.fontWeight) >= 600,
        italic: computed.fontStyle === 'italic', decoration: computed.textDecorationLine,
      }
    })
    doc.querySelectorAll('style').forEach(node => node.remove())
    for (const [index, element] of elements.entries()) {
      const style = styles[index]!
      element.removeAttribute('id'); element.removeAttribute('style')
      element.className = [...element.classList].filter(value => editorialClasses.has(value)
        || (element.localName === 'code' && /^language-[a-z0-9_+-]{1,40}$/i.test(value) && !value.startsWith('language-galaris-'))).join(' ')
      if (!element.className) element.removeAttribute('class')
      // Keep pre > code intact: wrapping it in font spans turns a code block
      // into ordinary paragraphs during CKEditor's conversion.
      if (element.closest('pre')) continue
      for (const [key, value] of style.inline) {
        if (validEditorialStyle(key, value) && !['rgba(0, 0, 0, 0)', 'transparent', 'normal', 'start', '16px', 'none', '0px none rgb(0, 0, 0)'].includes(value)) element.style.setProperty(key, value)
      }
      if (!['TABLE', 'TBODY', 'THEAD', 'TFOOT', 'TR', 'UL', 'OL', 'IMG', 'HR', 'BR'].includes(element.tagName)
        && !element.querySelector('p,h1,h2,h3,h4,h5,h6,div,section,article,table,ul,ol,blockquote,pre,figure')) {
        for (const [enabled, tag] of [[style.bold, 'strong'], [style.italic, 'em'], [style.decoration.includes('underline'), 'u'], [style.decoration.includes('line-through'), 's']] as const) {
          if (!enabled || element.localName === tag || /^h[1-6]$/.test(element.localName)) continue
          const wrapper = doc.createElement(tag); wrapper.append(...element.childNodes); element.append(wrapper)
        }
        // CKEditor's font converters consume inline spans, not paragraph styles.
        if (element.localName !== 'span') {
          const span = doc.createElement('span')
          for (const key of ['color', 'font-family', 'font-size']) {
            const value = element.style.getPropertyValue(key)
            if (value) { span.style.setProperty(key, value); element.style.removeProperty(key) }
          }
          if (span.getAttribute('style')) { span.append(...element.childNodes); element.append(span) }
        }
      }
    }
    const imported = new Map<string, Promise<string>>()
    for (const image of [...doc.body.querySelectorAll('img')]) {
      options.signal.throwIfAborted()
      const source = images.get(image.getAttribute('data-paste-image') ?? '') ?? ''
      image.removeAttribute('data-paste-image')
      try {
        if (attachmentReference(source)) { image.setAttribute('src', source); continue }
        if (imported.size >= 50 && !imported.has(source)) throw new Error('Too many pasted images')
        let pending = imported.get(source)
        if (!pending) {
          pending = (async () => {
            if (/^data:image\/(png|jpeg|webp|gif);base64,/i.test(source) && options.upload) {
              const [header, encoded = ''] = source.split(',', 2)
              if (encoded.length > 14_000_000) throw new Error('Image too large')
              const type = header!.slice(5).split(';')[0]!
              const bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0))
              if (bytes.length > 10_000_000) throw new Error('Image too large')
              return options.upload(new File([bytes], 'pasted-image.' + type.split('/')[1], { type }), options.signal, () => {})
            }
            if (source.startsWith('https://') && options.importImage) return options.importImage(source, options.signal)
            throw new Error('Image source unavailable')
          })()
          imported.set(source, pending)
        }
        const uri = await pending
        options.signal.throwIfAborted()
        image.setAttribute('src', uri)
      } catch (error) {
        if (options.signal.aborted) throw error
        const label = doc.createElement('span'); label.textContent = image.alt || options.imageLabel
        image.replaceWith(label); options.imageFailed()
      }
    }
    // Layout containers become ordinary paragraphs or groups of native blocks.
    for (const container of [...doc.body.querySelectorAll('div,section,article,main,header,footer,aside')].reverse()) {
      if (container.querySelector('p,h1,h2,h3,h4,h5,h6,ul,ol,table,blockquote,pre,figure')) container.replaceWith(...container.childNodes)
      else {
        const paragraph = doc.createElement('p')
        paragraph.setAttribute('style', container.getAttribute('style') ?? '')
        paragraph.append(...container.childNodes); container.replaceWith(paragraph)
      }
    }
    return sanitizeRichHtml(doc.body.innerHTML, 'document')
  } finally { frame.remove() }
}
