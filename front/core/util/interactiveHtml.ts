import { editorialClasses, validEditorialStyle } from './editorialHtmlStyle'
import { chartAttribute } from './editorialChart'
import { protectSvg, restoreSvgFigures, svgCode, svgFigureSource } from './editorialSvg'

const editorialTags = new Set('p h1 h2 h3 h4 h5 h6 strong em u s b i del blockquote ul ol li hr a table thead tbody tfoot tr th td pre code br mark span img figure figcaption caption colgroup col sub sup'.split(' '))

/** Internal editor transport only: Source and saved documents keep ordinary HTML. */
export function protectInteractiveHtml(html: string): string {
  const doc = new DOMParser().parseFromString('<body>' + html, 'text/html')
  const interactive = (node: Node): boolean => {
    if (!(node instanceof Element)) return false
    if (node.localName === 'figure' && node.querySelector(':scope > ' + svgCode)) return false
    return [node, ...node.querySelectorAll('*')].some(element => !editorialTags.has(element.localName)
      || [...element.attributes].some(attribute => attribute.name === 'id' || attribute.name.startsWith('on') || attribute.name.startsWith('data-dataset'))
      || [...element.classList].some(name => !editorialClasses.has(name) && !(element.localName === 'code' && /^language-[a-zA-Z0-9_+-]{1,40}$/.test(name)))
      || (element.getAttribute('style') ?? '').split(';').some(declaration => {
        if (!declaration.trim()) return false
        const colon = declaration.indexOf(':')
        return colon < 0 || !validEditorialStyle(declaration.slice(0, colon).trim().toLowerCase(), declaration.slice(colon + 1).trim().toLowerCase())
      }))
  }
  // CSS selectors, scripts and cross-object SVG references can share document state.
  // Keep that region together rather than guessing dependencies from arbitrary code.
  const sharesDependencies = (element: Element) => ['script', 'style'].includes(element.localName)
    || [...element.attributes].some(attribute => attribute.name.startsWith('on')
      || /url\(\s*['"]?#/i.test(attribute.value)
      || element.localName !== 'a' && ['href', 'xlink:href'].includes(attribute.name) && attribute.value.startsWith('#'))
  const chartsInLegacyRegion = new Map<Element, Element>()
  const wrap = (nodes: ChildNode[]): void => {
    const region = doc.createElement('template')
    const pre = doc.createElement('pre'), code = doc.createElement('code')
    code.className = 'language-galaris-raw-html'
    nodes[0]!.before(pre)
    region.content.append(...nodes)
    // When an opaque region spans a chart, keep its SVG in that region's HTML.
    for (const [placeholder, svg] of chartsInLegacyRegion) {
      if (region.content.contains(placeholder)) placeholder.replaceWith(svg)
    }
    code.textContent = region.innerHTML
    pre.append(code)
  }
  const figures = new Map<Element, Element>()
  for (const element of doc.body.children) {
    const svg = svgFigureSource(element)
    if (svg && (element === svg || ![element, ...element.querySelectorAll('*')].some(child =>
      child !== svg && !svg.contains(child) && sharesDependencies(child)))) figures.set(element, svg)
  }
  const hasUnscopedDependencies = [...doc.body.children].some(element =>
    element.localName !== 'section' && !figures.has(element)
    && [element, ...element.querySelectorAll('*')].some(sharesDependencies))
  for (const svg of figures.values()) {
    if (!hasUnscopedDependencies) protectSvg(svg)
    else if (svg.hasAttribute(chartAttribute)) chartsInLegacyRegion.set(protectSvg(svg), svg)
  }
  if (!hasUnscopedDependencies) {
    for (const section of doc.body.querySelectorAll(':scope > section')) wrap([section])
  }
  const nodes = [...doc.body.childNodes]
  const first = nodes.findIndex(interactive), last = nodes.length - 1 - [...nodes].reverse().findIndex(interactive)
  if (first < 0) return doc.body.innerHTML
  if (hasUnscopedDependencies) wrap(nodes.slice(first, last + 1))
  else {
    let start = -1, end = -1
    nodes.forEach((node, index) => {
      if (interactive(node)) { if (start < 0) start = index; end = index }
      else if (node.textContent?.trim() || node instanceof Element) {
        if (start >= 0) wrap(nodes.slice(start, end + 1))
        start = -1
      }
    })
    if (start >= 0) wrap(nodes.slice(start, end + 1))
  }
  return doc.body.innerHTML
}

export function restoreInteractiveHtml(html: string): string {
  const doc = new DOMParser().parseFromString('<body>' + html, 'text/html')
  restoreSvgFigures(doc.body)
  doc.querySelectorAll('pre > code.language-galaris-raw-html').forEach(code => {
    const template = doc.createElement('template')
    template.innerHTML = code.textContent ?? ''
    code.parentElement!.replaceWith(template.content)
  })
  return doc.body.innerHTML
}

/** Static readers and exports never reveal executable source or start scripts. */
export function hideInteractiveSource(root: HTMLElement, fallback: string): void {
  root.querySelectorAll('pre > code.language-galaris-app, pre > code.language-galaris-raw-html').forEach(code => {
    const label = root.ownerDocument.createElement('p')
    label.textContent = fallback
    if (code.classList.contains('language-galaris-app')) {
      try {
        const value = JSON.parse(code.textContent ?? '') as { title?: unknown }
        if (typeof value.title === 'string') label.textContent = value.title
      } catch { /* Invalid source remains opaque. */ }
    }
    code.parentElement!.replaceWith(label)
  })
}
