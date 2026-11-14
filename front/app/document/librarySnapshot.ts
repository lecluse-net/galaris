/** Reuse unchanged JSON records so refreshing one document leaves its neighbours alone. */
export function reconcileLibrarySnapshot<T>(previous: T[], incoming: T[], key: (value: T) => string): T[] {
  const existing = new Map(previous.map(value => [key(value), value]))
  const reconciled = incoming.map(value => {
    const current = existing.get(key(value))
    return current && JSON.stringify(current) === JSON.stringify(value) ? current : value
  })
  return previous.length === reconciled.length && reconciled.every((value, index) => value === previous[index])
    ? previous : reconciled
}

/** Preserve every unchanged subtree, including its node and children identities. */
export function reconcileLibraryTree<T extends { id: string; children?: T[] }>(previous: T[], incoming: T[]): T[] {
  const existing = new Map(previous.map(node => [node.id, node]))
  const result = incoming.map(node => {
    const current = existing.get(node.id)
    if (!current) return node
    if (node.children) node.children = reconcileLibraryTree(current.children ?? [], node.children)
    const keys = Object.keys(node) as (keyof T)[]
    return keys.length === Object.keys(current).length && keys.every(key => current[key] === node[key]) ? current : node
  })
  return previous.length === result.length && result.every((node, index) => node === previous[index]) ? previous : result
}
