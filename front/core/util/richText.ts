import DOMPurify from 'dompurify'
import { editorialClasses, validEditorialStyle } from './editorialHtmlStyle'
import { hideInteractiveSource, protectInteractiveHtml } from './interactiveHtml'

export type ContentProfile = 'rich-text' | 'document'
export const CONTENT_PROFILE_VERSION = 1
export interface RichLinkTarget { uri: string; title: string; context: string }
export interface RichContentContribution {
  search: (query: string) => Promise<RichLinkTarget[]>
  href: (uri: string) => string | null
}
interface ContributionModule { default: RichContentContribution }
const contributions = Object.values(import.meta.glob<ContributionModule>('../../app/*/richContent.ts', { eager: true })).map(value => value.default)
const uuid = '[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
const internal = new RegExp(`^(?:(?:document|memory)://${uuid}|galaris://(?:goal|task)/${uuid}|galaris://agent/[1-9][0-9]*)$`)
const attachment = new RegExp(`^document://(${uuid})/attachments/(${uuid})$`)
export function attachmentReference(uri: string): [string, string] | null {
  const match = attachment.exec(uri)
  return match ? [match[1]!, match[2]!] : null
}
export function validRichLink(uri: string): boolean {
  if (/[\s\\]/.test(uri) || [...uri].some(char => char.charCodeAt(0) < 32)) return false
  if (internal.test(uri) || attachment.test(uri)) return true
  try {
    const url = new URL(uri)
    return (['http:', 'https:'].includes(url.protocol) ? Boolean(url.hostname) : url.protocol === 'mailto:' && Boolean(url.pathname)) && !url.username && !url.password
  } catch { return false }
}
export function richLinkHref(uri: string): string | null {
  if (!validRichLink(uri)) return null
  if (attachment.test(uri)) return contributions.map(value => value.href(uri)).find(Boolean) ?? null
  if (!internal.test(uri)) return uri
  return contributions.map(value => value.href(uri)).find(Boolean) ?? null
}
export async function searchRichLinks(query: string): Promise<RichLinkTarget[]> {
  const results = await Promise.allSettled(contributions.map(value => value.search(query)))
  if (results.length && results.every(value => value.status === 'rejected')) throw new Error('Content search unavailable')
  return results.flatMap(value => value.status === 'fulfilled' ? value.value : [])
}
export function sanitizeRichHtml(html: string, profile: ContentProfile = 'rich-text'): string {
  if (profile === 'document') html = protectInteractiveHtml(html)
  const clean = DOMPurify.sanitize(html, {
    ALLOWED_TAGS: 'p h1 h2 h3 h4 h5 h6 strong em u s blockquote ul ol li hr a table thead tbody tfoot tr th td pre code br mark span figure figcaption caption colgroup col sub sup b i del'.split(' ').concat(profile === 'document' ? ['img'] : []),
    ALLOWED_ATTR: ['href', 'title', 'rel', 'target', 'start', 'colspan', 'rowspan', 'colwidth', 'class', 'src', 'alt', 'width', 'style', 'data-color', 'data-rich-reference', 'height', 'value', 'reversed'],
    ADD_ATTR: ['data-code-lines', 'data-code-nowrap', ],
    FORCE_BODY: true,
    ALLOW_DATA_ATTR: false,
    ADD_URI_SAFE_ATTR: ['start', 'colspan', 'rowspan', 'colwidth', 'width', 'height', 'value', 'data-color', 'data-code-lines', 'data-code-nowrap', 'type', 'async', 'defer'],
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|document:\/\/|memory:\/\/|galaris:\/\/)/,
  })
  const doc = new DOMParser().parseFromString('<body>' + clean, 'text/html')
  for (const element of doc.body.querySelectorAll<HTMLElement>('*')) {
    for (const attribute of ['data-code-lines', 'data-code-nowrap']) {
      if (element.tagName !== 'CODE' || element.getAttribute(attribute) !== 'true') element.removeAttribute(attribute)
    }
    for (const attribute of ['start', 'colspan', 'rowspan', 'width', 'height', 'value']) {
      const raw = element.getAttribute(attribute)
      if (raw !== null && (!/^\d+$/.test(raw) || Number(raw) < 1 || Number(raw) > (element.tagName === 'IMG' && ['width', 'height'].includes(attribute) ? 16000 : 1000))) element.removeAttribute(attribute)
    }
    const colwidth = element.getAttribute('colwidth')
    if (colwidth !== null && !colwidth.split(',').every(value => /^\d+$/.test(value) && Number(value) <= 1600)) element.removeAttribute('colwidth')
    if (element.hasAttribute('style')) {
      const accepted = (element.getAttribute('style') ?? '').split(';').flatMap(declaration => {
        const colon = declaration.indexOf(':')
        const key = declaration.slice(0, colon).trim().toLowerCase(), value = declaration.slice(colon + 1).trim().toLowerCase()
        return colon > 0 && validEditorialStyle(key, value) ? [[key, value] as const] : []
      })
      element.removeAttribute('style')
      if (accepted.length) element.setAttribute('style', accepted.sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => key + ': ' + value).join('; '))
    }
    if (element.hasAttribute('class')) {
      const classes = [...element.classList].filter(value => editorialClasses.has(value) || element.tagName === 'CODE' && /^language-[a-zA-Z0-9_+-]{1,40}$/.test(value))
      if (classes.length) element.className = classes.join(' ')
      else element.removeAttribute('class')
    }
  }
  for (const element of doc.body.querySelectorAll('b,i,del')) {
    const replacement = doc.createElement(({ B: 'strong', I: 'em', DEL: 's' } as Record<string, string>)[element.tagName]!)
    for (const attribute of element.attributes) replacement.setAttribute(attribute.name, attribute.value)
    replacement.append(...element.childNodes)
    element.replaceWith(replacement)
  }
  for (const link of doc.body.querySelectorAll('a')) {
    const canonical = link.getAttribute('data-rich-reference')
    if (canonical && validRichLink(canonical)) link.setAttribute('href', canonical)
    link.removeAttribute('data-rich-reference')
    if (!validRichLink(link.getAttribute('href') ?? '')) link.removeAttribute('href')
    link.setAttribute('rel', 'noopener noreferrer')
    link.setAttribute('target', '_blank')
  }
  for (const image of doc.body.querySelectorAll('img')) {
    if (!attachmentReference(image.getAttribute('src') ?? '')) image.remove()
  }
  for (const figure of doc.body.querySelectorAll('figure.image,span.image-inline')) {
    if (!figure.querySelector('img') && !figure.textContent?.trim()) figure.remove()
  }
  if (!doc.body.textContent?.replaceAll('\u00a0', ' ').trim() && !doc.body.querySelector('table,hr,img')) return ''
  return doc.body.innerHTML
}
export function richTextExcerpt(html: string): string {
  const doc = new DOMParser().parseFromString('<body>' + sanitizeRichHtml(html, 'document'), 'text/html')
  hideInteractiveSource(doc.body, '')
  doc.querySelectorAll('script').forEach(script => script.remove())
  for (const block of doc.body.querySelectorAll('p,li,tr,h1,h2,h3,pre,br')) block.append('\n')
  return doc.body.textContent?.trim() ?? ''
}
