import DOMPurify from 'dompurify'
import { marked } from 'marked'

export function resourcePreviewText(description: string): string {
  const content = DOMPurify.sanitize(marked.parse(description, { async: false }), {
    RETURN_DOM_FRAGMENT: true,
    ALLOWED_TAGS: ['p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li', 'table', 'tr', 'th', 'td', 'pre', 'code', 'a', 'strong', 'em', 'span'],
    ALLOWED_ATTR: [],
  })
  for (const block of content.querySelectorAll('p,div,br,h1,h2,h3,h4,h5,h6,blockquote,li,tr,th,td,pre')) block.append(' ')
  return content.textContent?.replace(/\s+/g, ' ').trim() ?? ''
}
