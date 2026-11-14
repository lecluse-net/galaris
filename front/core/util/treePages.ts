import type { QTreeNode } from 'quasar'

export const TREE_PAGE_SIZE = 100
const prefix = 'virtual-tree-page:'

export interface TreePage {
  parent: string
  offset: number
  size: number
}

/** Stable identities keep an open range mounted when the collection's total changes. */
export function treePageKey(page: TreePage): string {
  return prefix + JSON.stringify([page.parent, page.offset, page.size])
}

export function treePageFromKey(key: string): TreePage | null {
  if (!key.startsWith(prefix)) return null
  try {
    const value: unknown = JSON.parse(key.slice(prefix.length))
    if (!Array.isArray(value) || value.length !== 3) return null
    const [parent, offset, size]: unknown[] = value
    return typeof parent === 'string' && typeof offset === 'number' && Number.isSafeInteger(offset) && offset >= 0
      && typeof size === 'number' && Number.isSafeInteger(size) && size >= TREE_PAGE_SIZE
      ? { parent, offset, size } : null
  } catch { return null }
}

/** Even a million entries produce at most 100 virtual folders at each level. */
export function treePages(parent: string, total: number, within?: TreePage): TreePage[] {
  const offset = within?.offset ?? 0
  const end = Math.min(total, within ? offset + within.size : total)
  const count = Math.max(0, end - offset)
  if (!count) return []
  let size = TREE_PAGE_SIZE
  while (Math.ceil(count / size) > TREE_PAGE_SIZE) size *= TREE_PAGE_SIZE
  return Array.from({ length: Math.ceil(count / size) }, (_, index) => ({ parent, offset: offset + index * size, size }))
}

/** The first virtual leaf reuses the collection's initial, bounded metadata read. */
export function treePageDataKey(key: string): string {
  const page = treePageFromKey(key)
  return page?.offset === 0 && page.size === TREE_PAGE_SIZE ? page.parent : key
}

/** Page already available metadata without mounting every sibling or expanding ranges implicitly. */
export function virtualTreeNodes(nodes: readonly QTreeNode[], nodeKey: string, expanded: readonly string[], parent = 'local-tree:root'): QTreeNode[] {
  const open = new Set(expanded)
  function item(node: QTreeNode): QTreeNode {
    if (node.header === 'virtual-range' || !node.children?.length) return node
    return { ...node, children: siblings(node.children, 'local-tree:' + String(node[nodeKey])) }
  }
  function siblings(values: readonly QTreeNode[], key: string, within?: TreePage): QTreeNode[] {
    if (values.length <= TREE_PAGE_SIZE && !within) return values.map(item)
    return treePages(key, values.length, within).map(page => {
      const id = treePageKey(page)
      const children = !open.has(id) ? [{ [nodeKey]: id + ':placeholder', label: '', disabled: true }]
        : page.size > TREE_PAGE_SIZE ? siblings(values, key, page)
          : values.slice(page.offset, Math.min(values.length, page.offset + page.size)).map(item)
      return { [nodeKey]: id, label: `${page.offset + 1}–${Math.min(values.length, page.offset + page.size)}`,
        page, total: values.length, header: 'virtual-range', selectable: false, children }
    })
  }
  return siblings(nodes, parent)
}

/** Reveal an existing selection through its virtual ranges without opening other pages. */
export function treePageAncestors(nodes: readonly QTreeNode[], nodeKey: string, selected: string, parent = 'local-tree:root'): string[] | null {
  for (let index = 0; index < nodes.length; index++) {
    const node = nodes[index]!
    const key = String(node[nodeKey])
    const below = node.children ? treePageAncestors(node.children, nodeKey, selected, 'local-tree:' + key) : null
    if (key !== selected && !below) continue
    const ranges: string[] = []
    if (nodes.length > TREE_PAGE_SIZE) {
      let range = treePages(parent, nodes.length).find(page => index >= page.offset && index < page.offset + page.size)!
      ranges.push(treePageKey(range))
      while (range.size > TREE_PAGE_SIZE) {
        range = treePages(parent, nodes.length, range).find(page => index >= page.offset && index < page.offset + page.size)!
        ranges.push(treePageKey(range))
      }
    }
    return [...ranges, ...(below ? [key, ...below] : [])]
  }
  return null
}
