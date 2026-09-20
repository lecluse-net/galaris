import { editorialClasses, validEditorialStyle } from './editorialHtmlStyle'

const editorialTags = new Set('p h1 h2 h3 h4 h5 h6 strong em u s b i del blockquote ul ol li hr a table thead tbody tfoot tr th td pre code br mark span img figure figcaption caption colgroup col sub sup'.split(' '))

/** Internal editor transport only: Source and saved documents keep ordinary HTML. */
export function protectInteractiveHtml(html: string): string {
  const doc = new DOMParser().parseFromString('<body>' + html, 'text/html')
  const nodes = [...doc.body.childNodes]
  const interactive = (node: Node): boolean => {
    if (!(node instanceof Element)) return false
    return [node, ...node.querySelectorAll('*')].some(element => !editorialTags.has(element.localName)
      || [...element.attributes].some(attribute => attribute.name === 'id' || attribute.name.startsWith('on') || attribute.name.startsWith('data-dataset'))
      || [...element.classList].some(name => !editorialClasses.has(name) && !(element.localName === 'code' && /^language-[a-zA-Z0-9_+-]{1,40}$/.test(name)))
      || (element.getAttribute('style') ?? '').split(';').some(declaration => {
        if (!declaration.trim()) return false
        const colon = declaration.indexOf(':')
        return colon < 0 || !validEditorialStyle(declaration.slice(0, colon).trim().toLowerCase(), declaration.slice(colon + 1).trim().toLowerCase())
      }))
  }
  const first = nodes.findIndex(interactive), last = nodes.length - 1 - [...nodes].reverse().findIndex(interactive)
  if (first < 0) return doc.body.innerHTML
  const region = doc.createElement('div')
  const pre = doc.createElement('pre'), code = doc.createElement('code')
  code.className = 'language-galaris-raw-html'
  nodes[first]!.before(pre)
  nodes.slice(first, last + 1).forEach(node => region.append(node))
  code.textContent = region.innerHTML
  pre.append(code)
  return doc.body.innerHTML
}

export function restoreInteractiveHtml(html: string): string {
  const doc = new DOMParser().parseFromString('<body>' + html, 'text/html')
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
