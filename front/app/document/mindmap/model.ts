export interface MindMapNode {
  id: string
  parent: string | null
  title: string
  note?: string
  link?: string
  icon?: string
  body_html?: string
  checked?: boolean | null
}

export interface MindMap {
  version: 1
  nodes: MindMapNode[]
  theme?: { id: string; version: number } | null
  background_color?: string | null
}

export function mindMapNodeLabel(node: MindMapNode, documentTitle: string | undefined, untitled: string): string {
  return node.title || (node.parent === null ? documentTitle : undefined) || untitled
}

export const maxNodes = 2000
export const maxDepth = 48
const nodeKey = /^[A-Za-z0-9_-]{1,80}$/
const paletteKey = /^[a-z][a-z0-9-]{0,63}$/

export function isHexColor(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)
}

function isNode(value: unknown): value is MindMapNode {
  if (typeof value !== 'object' || value === null) return false
  const node = value as Partial<MindMapNode>
  return typeof node.id === 'string' && nodeKey.test(node.id)
    && (node.parent === null || (typeof node.parent === 'string' && nodeKey.test(node.parent)))
    && typeof node.title === 'string' && Array.from(node.title).length <= 500
    && (node.checked == null || typeof node.checked === 'boolean')
    && (node.note === undefined || (typeof node.note === 'string' && Array.from(node.note).length <= 16000))
    && (node.link === undefined || (typeof node.link === 'string' && Array.from(node.link).length <= 2048))
    && (node.icon === undefined || (typeof node.icon === 'string' && node.icon.length <= 1_000_000))
    && (node.body_html === undefined || (typeof node.body_html === 'string' && Array.from(node.body_html).length <= 128_000))
}

export function nodesByParent(nodes: MindMapNode[]): Map<string | null, MindMapNode[]> {
  const children = new Map<string | null, MindMapNode[]>()
  for (const node of nodes) {
    const siblings = children.get(node.parent)
    if (siblings) siblings.push(node)
    else children.set(node.parent, [node])
  }
  return children
}

export function parseMindMap(source: string): MindMap | null {
  try {
    const value = JSON.parse(source) as Partial<MindMap> | null
    if (value?.version !== 1 || !Array.isArray(value.nodes) || value.nodes.length > maxNodes || !value.nodes.every(isNode)) return null
    const theme = value.theme
    const backgroundColor = value.background_color
    if (theme != null && (typeof theme.id !== 'string' || !paletteKey.test(theme.id) || !Number.isSafeInteger(theme.version) || theme.version < 1)) return null
    if (backgroundColor != null && !isHexColor(backgroundColor) && (typeof backgroundColor !== 'string' || !paletteKey.test(backgroundColor))) return null
    const children = nodesByParent(value.nodes)
    const roots = children.get(null)
    if (roots?.length !== 1 || new Set(value.nodes.map(node => node.id)).size !== value.nodes.length) return null
    let count = 0
    function visit(nodes: MindMapNode[], depth: number): boolean {
      if (depth > maxDepth) return nodes.length === 0
      count += nodes.length
      return nodes.every(node => visit(children.get(node.id) ?? [], depth + 1))
    }
    return visit(roots, 0) && count === value.nodes.length ? { version: 1, nodes: value.nodes, theme, background_color: backgroundColor } : null
  } catch {
    return null
  }
}
