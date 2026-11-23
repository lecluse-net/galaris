import DOMPurify from 'dompurify'

const svgNamespace = 'http://www.w3.org/2000/svg'
export const svgCode = 'pre > code.language-galaris-svg'
const svgTags = new Set('svg g path rect circle ellipse line polyline polygon text tspan defs linearGradient radialGradient stop clipPath mask use symbol title desc style'.split(' '))
const urlReference = /url\(\s*(?:"([^"]*)"|'([^']*)'|([^\s)]*))\s*\)/gi

/** Only local definitions are available to a standalone figure. */
export function isStandaloneSvg(svg: Element): boolean {
  if (svg.namespaceURI !== svgNamespace || svg.localName !== 'svg') return false
  const elements = [svg, ...svg.querySelectorAll('*')]
  const ids = new Set(elements.flatMap(element => element.id ? [element.id] : []))
  const local = (reference: string) => reference.startsWith('#') && ids.has(reference.slice(1))
  const referencesAreLocal = (value: string) => {
    const css = value.replace(/\/\*[\s\S]*?\*\//g, '')
    return !/\\|@import\b/i.test(css)
      && [...css.matchAll(urlReference)].every(match => local(match[1] ?? match[2] ?? match[3] ?? ''))
  }
  return elements.every(element => element.namespaceURI === svgNamespace && svgTags.has(element.localName)
    && [...element.attributes].every(({ name, value }) => {
      if (/^(?:on|data-dataset)/i.test(name) || /^(?:src|xml:base)$/i.test(name)) return false
      if (/^(?:xlink:)?href$/i.test(name)) return local(value)
      return !/url\s*\(|\\/i.test(value) || referencesAreLocal(value)
    })
    && (element.localName !== 'style' || referencesAreLocal(element.textContent ?? '')))
}

export function svgFigureSource(element: Element): Element | null {
  if (element.localName === 'figure') {
    const [source, caption, ...rest] = element.children
    if (rest.length || (caption && caption.localName !== 'figcaption')
      || [...element.childNodes].some(child => child.nodeType === 3 && child.textContent?.trim())) return null
    return source && isStandaloneSvg(source) ? source : null
  }
  return isStandaloneSvg(element) ? element : null
}

export function protectSvg(source: Element): void {
  const doc = source.ownerDocument
  const pre = doc.createElement('pre')
  const code = doc.createElement('code')
  code.className = 'language-galaris-svg'
  code.textContent = source.outerHTML
  pre.append(code)
  source.replaceWith(pre)
}

function readSvg(doc: Document, source: string): Element | null {
  const template = doc.createElement('template')
  template.innerHTML = source
  const svg = template.content.firstElementChild
  return svg && template.content.children.length === 1 && isStandaloneSvg(svg) ? svg : null
}

export function restoreSvgFigures(root: ParentNode): void {
  for (const code of root.querySelectorAll(svgCode)) {
    const svg = readSvg(code.ownerDocument, code.textContent ?? '')
    if (svg) code.parentElement!.replaceWith(svg)
  }
}

export function svgImage(doc: Document, source: string): HTMLImageElement | null {
  const original = readSvg(doc, source)
  if (!original) return null
  const template = doc.createElement('template')
  template.innerHTML = DOMPurify.sanitize(original.outerHTML, {
    USE_PROFILES: { svg: true }, ADD_TAGS: ['style', 'use', 'symbol'],
  })
  const clean = template.content.firstElementChild
  if (!clean || !isStandaloneSvg(clean)) return null
  const image = doc.createElement('img')
  image.className = 'editorial-svg-image'
  image.alt = original.getAttribute('aria-label') ?? original.querySelector('title')?.textContent ?? ''
  image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(clean))
  return image
}

export function renderSvgFigures(root: ParentNode): void {
  for (const code of root.querySelectorAll(svgCode)) {
    const image = svgImage(code.ownerDocument, code.textContent ?? '')
    if (image) code.parentElement!.replaceWith(image)
  }
}
