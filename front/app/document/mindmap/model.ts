export interface MindMapNode {
  id: string
  parent: string | null
  title: string
  note?: string
  link?: string
  icon?: string
  body_html?: string
  checked?: boolean | null
  value?: string | null
}

export interface MindMap {
  version: 1
  nodes: MindMapNode[]
  connectors?: MindMapConnector[]
  theme?: { id: string; version: number } | null
  background_color?: string | null
}

export interface MindMapConnector {
  source: string
  target: string
  label: string
}

export function connectorKey({ source, target }: MindMapConnector): string {
  return source < target ? `${source}:${target}` : `${target}:${source}`
}

export const maxConnectors = 1000
export const maxConnectorLabelLength = 120

export function connectorDescriptions(map: MindMap): ReadonlyMap<string, string[]> {
  const labels = new Map(map.nodes.map(node => [node.id, node.title || node.id]))
  const descriptions = new Map<string, string[]>()
  for (const { source, target, label } of map.connectors ?? []) {
    const description = `${label} → ${labels.get(target)}`
    const sourceDescriptions = descriptions.get(source)
    if (sourceDescriptions) sourceDescriptions.push(description)
    else descriptions.set(source, [description])
  }
  return descriptions
}

function validConnectors(connectors: unknown, ids: ReadonlySet<string>): connectors is MindMapConnector[] {
  if (!Array.isArray(connectors) || connectors.length > maxConnectors) return false
  const pairs = new Set<string>()
  for (const entry of connectors) {
    if (typeof entry !== 'object' || entry === null) return false
    const connector = entry as Partial<MindMapConnector>
    const { source, target, label } = connector
    if (typeof source !== 'string' || typeof target !== 'string' || source === target || !ids.has(source) || !ids.has(target)
      || typeof label !== 'string' || !label.trim() || Array.from(label).length > maxConnectorLabelLength) return false
    pairs.add(connectorKey({ source, target, label }))
  }
  return pairs.size === connectors.length
}

export function mindMapNodeLabel(node: MindMapNode, documentTitle: string | undefined, untitled: string): string {
  return node.title || (node.parent === null ? documentTitle : undefined) || untitled
}

export const maxValueLength = 2048
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
    && (node.value == null || (typeof node.value === 'string' && Array.from(node.value).length <= maxValueLength))
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
    const ids = new Set(value.nodes.map(node => node.id))
    if (roots?.length !== 1 || ids.size !== value.nodes.length) return null
    if (value.connectors !== undefined && !validConnectors(value.connectors, ids)) return null
    let count = 0
    function visit(nodes: MindMapNode[], depth: number): boolean {
      if (depth > maxDepth) return nodes.length === 0
      count += nodes.length
      return nodes.every(node => visit(children.get(node.id) ?? [], depth + 1))
    }
    return visit(roots, 0) && count === value.nodes.length
      ? { version: 1, nodes: value.nodes, connectors: value.connectors, theme, background_color: backgroundColor } : null
  } catch {
    return null
  }
}
