import type { NavigationNode, NavigationTree } from './types'

/** Keep only the navigation branches available in the current context. */
export function filterNavigationTree(
  tree: NavigationTree,
  isVisible: (node: NavigationNode) => boolean,
): NavigationTree {
  const filtered: NavigationTree = {}
  for (const [key, node] of Object.entries(tree)) {
    if (!isVisible(node)) continue
    const children = node.children ? filterNavigationTree(node.children, isVisible) : {}
    const hasChildren = Object.keys(children).length > 0
    if (node.requiresVisibleChildren && !hasChildren) continue
    const { children: _, ...properties } = node
    filtered[key] = hasChildren ? { ...properties, children } : properties
  }
  return filtered
}

/** Merge a source tree into a target without retaining or mutating source-owned branches. */
export function mergeNavigationTrees(target: NavigationTree, source: NavigationTree): void {
  for (const [key, sourceNode] of Object.entries(source)) {
    const { children: sourceChildren, ...sourceProps } = sourceNode

    if (target[key]) {
      const targetNode = target[key]
      Object.assign(targetNode, sourceProps)

      if (sourceChildren) {
        if (!targetNode.children) targetNode.children = {}
        mergeNavigationTrees(targetNode.children, sourceChildren)
      }
      continue
    }

    const targetNode: NavigationNode = { ...sourceProps }
    if (sourceChildren) {
      const targetChildren: NavigationTree = {}
      mergeNavigationTrees(targetChildren, sourceChildren)
      targetNode.children = targetChildren
    }
    target[key] = targetNode
  }
}
