import { marked } from 'marked'

const formatting = new Set(['heading', 'list', 'blockquote', 'table', 'hr', 'code', 'codespan', 'strong', 'em', 'del', 'image'])

/** Recognize Markdown source without reinterpreting ordinary prose or rendered HTML. */
export function pastedMarkdownHtml(text: string, clipboardHtml: string): string | null {
  if (!text.trim() || text.length > 2_000_000) return null
  if (clipboardHtml) {
    const page = new DOMParser().parseFromString(clipboardHtml, 'text/html')
    // Source editors often copy literal Markdown inside pre/code/span wrappers.
    // Real formatted content keeps its HTML, including deliberately literal markers.
    if (page.querySelector('h1,h2,h3,h4,h5,h6,strong,b,em,i,u,s,del,ul,ol,table,blockquote,img,hr')) return null
  }
  const tokens = marked.lexer(text, { gfm: true })
  let markdown = false
  marked.walkTokens(tokens, token => {
    if (formatting.has(token.type) || (token.type === 'link' && token.raw.startsWith('['))) markdown = true
  })
  if (!markdown) return null
  const renderer = new marked.Renderer()
  // Preserve task completion when the editorial sanitizer removes form controls.
  renderer.checkbox = ({ checked }) => checked ? '☑ ' : '☐ '
  return marked.parser(tokens, { gfm: true, renderer })
}
