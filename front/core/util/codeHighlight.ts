import highlighter from 'highlight.js/lib/common'
import './solaireTheme'

// Bound automatic detection during editing; large blocks remain readable plain code.
const maxHighlightedLength = 50_000
const detectedLanguages = ['javascript', 'typescript', 'python', 'xml', 'css', 'json', 'bash', 'sql', 'yaml', 'java', 'cpp', 'php', 'ruby', 'go', 'diff']

export function highlightCode(source: string, language = ''): string | null {
  if (!source || source.length > maxHighlightedLength) return null
  if (!language || language === 'plaintext') return highlighter.highlightAuto(source, detectedLanguages).value
  if (!highlighter.getLanguage(language)) return null
  return highlighter.highlight(source, { language, ignoreIllegals: true }).value
}

/** Apply only to a sanitized display snapshot, never to stored HTML or CKEditor's DOM. */
export function highlightDocumentCode(root: ParentNode): void {
  root.querySelectorAll('pre code').forEach(code => {
    const language = [...code.classList].find(name => name.startsWith('language-'))?.slice(9)
    const highlighted = highlightCode(code.textContent ?? '', language)
    if (highlighted !== null) code.innerHTML = highlighted
    if (code.getAttribute('data-code-lines') === 'true') {
      const doc = code.ownerDocument
      let line = 1
      const marker = () => {
        const span = doc.createElement('span')
        span.className = 'galaris-code-line'
        span.dataset.codeLine = String(line++)
        span.setAttribute('aria-hidden', 'true')
        return span
      }
      const walker = doc.createTreeWalker(code, NodeFilter.SHOW_TEXT)
      const texts: Text[] = []
      while (walker.nextNode()) texts.push(walker.currentNode as Text)
      code.prepend(marker())
      for (const text of texts) {
        const parts = text.data.split('\n')
        if (parts.length < 2) continue
        const fragment = doc.createDocumentFragment()
        parts.forEach((part, index) => {
          if (index) fragment.append('\n', marker())
          fragment.append(part)
        })
        text.replaceWith(fragment)
      }
    }
  })
}

export interface CodeToken { start: number; end: number; className: string }

/** Highlight.js emits escaped text and spans; map their text offsets to CKEditor ranges. */
export function codeTokens(source: string, language: string): CodeToken[] {
  const highlighted = highlightCode(source, language)
  if (highlighted === null) return []
  const doc = new DOMParser().parseFromString('<body>' + highlighted, 'text/html')
  const tokens: CodeToken[] = []
  let offset = 0
  const visit = (node: Node, inheritedClass = '') => {
    if (node.nodeType === Node.TEXT_NODE) {
      const end = offset + (node.textContent?.length ?? 0)
      if (inheritedClass && end > offset) tokens.push({ start: offset, end, className: inheritedClass })
      offset = end
      return
    }
    const className = node instanceof Element
      ? [...node.classList].find(name => name.startsWith('hljs-')) ?? inheritedClass
      : inheritedClass
    node.childNodes.forEach(child => visit(child, className))
  }
  visit(doc.body)
  return tokens
}
