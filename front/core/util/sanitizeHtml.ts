/** Remove active HTML before rendering user-controlled rich text. */
export function sanitizeHtml(html: string): string {
  return sanitizeDocument(html, false)
}

const previewTags = new Set([
  'a', 'abbr', 'article', 'aside', 'b', 'blockquote', 'br', 'button', 'caption',
  'code', 'col', 'colgroup', 'dd', 'del', 'details', 'div', 'dl', 'dt', 'em',
  'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4',
  'h5', 'h6', 'header', 'hr', 'i', 'img', 'input', 'kbd', 'label', 'legend',
  'li', 'main', 'mark', 'meter', 'nav', 'ol', 'option', 'output', 'p', 'pre',
  'progress', 'q', 's', 'samp', 'section', 'select', 'small', 'span', 'strong',
  'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'textarea', 'tfoot', 'th',
  'thead', 'tr', 'u', 'ul', 'var',
])
const globalPreviewAttributes = new Set([
  'aria-label', 'aria-labelledby', 'aria-describedby', 'dir', 'for', 'id',
  'lang', 'role', 'title',
])
const previewAttributes: Record<string, Set<string>> = {
  a: new Set(['href']),
  button: new Set(['disabled', 'name', 'type', 'value']),
  col: new Set(['span']),
  form: new Set(['autocomplete', 'name']),
  img: new Set(['alt', 'decoding', 'height', 'loading', 'src', 'width']),
  input: new Set(['autocomplete', 'checked', 'disabled', 'max', 'maxlength', 'min', 'minlength', 'multiple', 'name', 'placeholder', 'readonly', 'required', 'step', 'type', 'value']),
  meter: new Set(['high', 'low', 'max', 'min', 'optimum', 'value']),
  option: new Set(['disabled', 'label', 'selected', 'value']),
  output: new Set(['for', 'name']),
  progress: new Set(['max', 'value']),
  select: new Set(['disabled', 'multiple', 'name', 'required', 'size']),
  td: new Set(['colspan', 'rowspan']),
  textarea: new Set(['cols', 'disabled', 'maxlength', 'minlength', 'name', 'placeholder', 'readonly', 'required', 'rows']),
  th: new Set(['colspan', 'rowspan', 'scope']),
}

function safePreviewUrl(tag: string, name: string, rawValue: string, preview: boolean): boolean {
  if (!preview && (name === 'src' || name === 'href')) {
    if (tag === 'img' && /^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(rawValue.trim())) return true
    try {
      // The URL parser follows browser normalization, including control characters.
      const url = new URL(rawValue, 'https://galaris.invalid/')
      return ['http:', 'https:'].includes(url.protocol)
        || (tag === 'a' && ['mailto:', 'tel:'].includes(url.protocol))
    } catch { return false }
  }
  const value = rawValue.trim()
  if (tag === 'img' && name === 'src') {
    return /^https:\/\//i.test(value)
      || /^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(value)
  }
  if (tag === 'a' && name === 'href') {
    return /^(?:https?:\/\/|mailto:|#)/i.test(value)
  }
  return true
}

/** Strict HTML allowlist for an isolated rich preview. */
export function sanitizePreviewHtml(html: string): string {
  return sanitizeDocument(html, true)
}

function sanitizeDocument(html: string, preview: boolean): string {
  const document = new DOMParser().parseFromString(html, 'text/html')
  document
    .querySelectorAll('script, style, iframe, object, embed, link, meta, base, svg, math')
    .forEach(node => node.remove())
  if (!preview) document.querySelectorAll('form, input, button, select, textarea').forEach(node => node.remove())

  for (const element of Array.from(document.body.querySelectorAll('*'))) {
    const tag = element.tagName.toLowerCase()
    if (!previewTags.has(tag)) {
      element.replaceWith(...Array.from(element.childNodes))
      continue
    }

    const allowed = previewAttributes[tag] ?? new Set<string>()
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase()
      if (
        (!globalPreviewAttributes.has(name) && !allowed.has(name) && !(name === 'class' && !preview))
        || (!preview && ['id', 'name', 'for'].includes(name))
        || !safePreviewUrl(tag, name, attribute.value, preview)
      ) {
        element.removeAttribute(attribute.name)
      }
    }

    if (tag === 'a') {
      element.setAttribute('target', '_blank')
      element.setAttribute('rel', 'noopener noreferrer')
    } else if (tag === 'img') {
      element.setAttribute('loading', 'lazy')
      element.setAttribute('decoding', 'async')
    } else if (tag === 'button') {
      // Generated forms remain demonstrable but cannot submit arbitrary actions.
      element.setAttribute('type', 'button')
    }
  }

  return document.body.innerHTML
}
