import type { NavigationNode, NavigationTree } from './types'

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
