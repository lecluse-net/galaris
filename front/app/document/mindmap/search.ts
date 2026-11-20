import { createEditorialMatcher } from '@/core/util/facade'
import type { MindMapNode } from './model'

type SearchField = 'title' | 'value' | 'note' | 'body_html'
type Match = { from: number; to: number }
type SearchTarget = { id: string; field: SearchField; matches: Match[]; text?: Text[] }
export type MindMapMatch = { target: SearchTarget; range: Match }

// Match across formatting runs within a paragraph. A block break or an atom
// separates runs, as in the editor, and markup and URLs are never searched.
function bodyText(html: string): Text[][] {
  const body = new DOMParser().parseFromString(html, 'text/html').body
  const runs: Text[][] = []
  let run: Text[] = []
  const separate = () => { if (run.length) runs.push(run); run = [] }
  function visit(node: Node): void {
    if (node instanceof Text) { if (node.length) run.push(node); return }
    if (!(node instanceof Element)) return
    if (node.matches('script, style, iframe, object, img, br, hr, video, audio, [data-math], pre:has(> code:is(.language-galaris-app, .language-galaris-raw-html))')) { separate(); return }
    const block = node.matches('p, h1, h2, h3, h4, h5, h6, div, li, pre, td, th, blockquote, figure, figcaption, caption')
    if (block) separate()
    node.childNodes.forEach(visit)
    if (block) separate()
  }
  visit(body)
  separate()
  return runs
}

export function searchMindMap(nodes: MindMapNode[], query: string, matchCase: boolean, wholeWords: boolean): MindMapMatch[] {
  if (!query) return []
  const find = createEditorialMatcher(query, matchCase, wholeWords)
  const targets: SearchTarget[] = []
  for (const node of nodes) {
    for (const field of ['title', 'value', 'note'] as const) {
      const text = node[field]
      if (text) targets.push({ id: node.id, field, matches: find(text) })
    }
    if (node.body_html) for (const text of bodyText(node.body_html)) {
      targets.push({ id: node.id, field: 'body_html', text, matches: find(text.map(run => run.data).join('')) })
    }
  }
  return targets.flatMap(target => target.matches.map(range => ({ target, range })))
}

export function replaceMindMapMatches(nodes: MindMapNode[], matches: MindMapMatch[], value: string): MindMapNode[] {
  const changed = new Map<string, MindMapNode>()
  const originals = new Map(nodes.map(node => [node.id, node]))
  for (const { target, range } of [...matches].reverse()) {
    const node = changed.get(target.id) ?? { ...originals.get(target.id)! }
    if (target.text) {
      const body = target.text[0]!.ownerDocument.body
      let offset = 0, inserted = false
      // Distribute the edit among original text nodes. Wrappers such as links,
      // emphasis and table cells retain their attributes and structure.
      for (const text of target.text) {
        const end = offset + text.length
        if (end > range.from && offset < range.to) {
          const from = Math.max(0, range.from - offset)
          text.replaceData(from, Math.min(end, range.to) - offset - from, inserted ? '' : value)
          inserted = true
        }
        offset = end
        if (end >= range.to) break
      }
      node.body_html = body.innerHTML
    } else {
      const field = target.field, text = node[field] ?? ''
      node[field] = text.slice(0, range.from) + value + text.slice(range.to)
    }
    changed.set(node.id, node)
  }
  return nodes.map(node => changed.get(node.id) ?? node)
}
