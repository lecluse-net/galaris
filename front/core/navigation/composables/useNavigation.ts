/**
 * Load and manipulate module-provided navigation trees.
 *
 * Navigation is a keyed tree:
 * - keys are node IDs;
 * - nodes contain label, icon, to, href, order, children, and related metadata;
 * - trees use objects rather than arrays.
 */

import { computed, ref } from 'vue'
import type { NavigationTree, NavigationNode, NavigationNodeWithPath, NavigationModule } from '../types'
import { mergeNavigationTrees } from '../tree'
import { modules as activeModules } from '../../../modules'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'

/** Loaded module cache. */
const modulesCache = ref<Record<string, NavigationModule>>({})

/** Loading flag. */
const isLoading = ref(false)

/** Loading error. */
const loadError = ref<string | null>(null)

/**
 * Load every navigation.ts file from active modules.
 */
export function useNavigation() {
  // Privilege store used for visibility checks.
  const privilegeStore = usePrivilegeStore()

  // Lazy module loading.
  function loadModules() {
    if (Object.keys(modulesCache.value).length > 0) return

    isLoading.value = true
    loadError.value = null

    try {
      // Load navigation definitions with import.meta.glob.
      const allModules = import.meta.glob<NavigationModule>('@/**/navigation.ts', { eager: true })

      for (const modulePath of activeModules) {
        const moduleKey = Object.keys(allModules).find(key =>
          key.endsWith(modulePath + '/navigation.ts')
        )

        if (moduleKey) {
          modulesCache.value[modulePath] = allModules[moduleKey]
        }
      }
    } catch (err) {
      loadError.value = err instanceof Error ? err.message : 'Navigation loading failed'
      console.error('Failed to load navigation:', err)
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Return whether the user has the privileges required by a node.
   */
  function hasRequiredPrivileges(node: NavigationNode): boolean {
    if (!node.privileges || node.privileges.length === 0) {
      return true // Nodes without required privileges are visible to everyone.
    }

    // At least one required privilege grants access (OR semantics).
    return node.privileges.some(privilege =>
      privilegeStore.hasPrivilege(privilege)
    )
  }

  /**
   * Filter a navigation tree to nodes visible to the user.
   */
  function filterTreeByPrivileges(tree: NavigationTree): NavigationTree {
    const filtered: NavigationTree = {}

    for (const [key, node] of Object.entries(tree)) {
      // Check required privileges.
      if (!hasRequiredPrivileges(node)) {
        continue // Skip the node and all its descendants.
      }

      // Check the custom visibility predicate.
      if (!isVisible(node)) {
        continue
      }

      // Clone the node.
      const filteredNode: NavigationNode = { ...node }

      // Filter descendants recursively.
      if (node.children) {
        const filteredChildren = filterTreeByPrivileges(node.children)
        if (Object.keys(filteredChildren).length > 0) {
          filteredNode.children = filteredChildren
        } else {
          delete filteredNode.children
        }
      }

      filtered[key] = filteredNode
    }

    return filtered
  }

  /**
   * Return navigation trees merged and filtered by privileges.
   */
  const allTrees = computed<NavigationTree>(() => {
    loadModules()

    const merged: NavigationTree = {}

    for (const module of Object.values(modulesCache.value)) {
      if (module?.default && typeof module.default === 'object') {
        // Merge trees recursively.
        mergeNavigationTrees(merged, module.default)
      }
    }

    // Filter by privileges.
    return filterTreeByPrivileges(merged)
  })

  /**
   * Return a subtree by root key.
   */
  function getTreeByRoot(rootKey: string): NavigationTree {
    const trees = allTrees.value
    const rootNode = trees[rootKey]

    if (!rootNode) {
      return {}
    }

    // Return root children when present; otherwise return the root itself.
    if (rootNode.children && Object.keys(rootNode.children).length > 0) {
      return rootNode.children
    }

    return { [rootKey]: rootNode }
  }

  /**
   * Return tree nodes sorted by display order.
   */
  function getSortedNodes(tree: NavigationTree): NavigationNodeWithPath[] {
    const entries = Object.entries(tree)

    return entries
      .map(([key, node]) => ({
        ...node,
        key,
        path: key,
        depth: 0,
        childrenKeys: node.children ? Object.keys(node.children) : undefined
      }))
      .sort((a, b) => (a.order ?? 99) - (b.order ?? 99))
  }

  /**
   * Return a node's children.
   */
  function getChildren(node: NavigationNode, parentPath: string, depth: number): NavigationNodeWithPath[] {
    if (!node.children) {
      return []
    }

    return Object.entries(node.children)
      .map(([key, childNode]) => ({
        ...childNode,
        key,
        path: `${parentPath}.${key}`,
        depth,
        childrenKeys: childNode.children ? Object.keys(childNode.children) : undefined
      }))
      .sort((a, b) => (a.order ?? 99) - (b.order ?? 99))
  }

  /**
   * Flatten a tree for lookup.
   */
  const flatNodes = computed<NavigationNodeWithPath[]>(() => {
    return flattenTree(allTrees.value, '', 0)
  })

  /**
   * Find a node by path, for example 'administration.settings'.
   */
  function findByPath(path: string): NavigationNodeWithPath | null {
    const parts = path.split('.')
    let current: NavigationTree | undefined = allTrees.value
    let currentNode: NavigationNode | undefined
    let currentDepth = 0

    for (const part of parts) {
      if (!current || !current[part]) {
        return null
      }
      currentNode = current[part]
      current = currentNode.children
      currentDepth++
    }

    if (!currentNode) {
      return null
    }

    return {
      ...currentNode,
      key: parts[parts.length - 1],
      path,
      depth: currentDepth - 1,
      childrenKeys: currentNode.children ? Object.keys(currentNode.children) : undefined
    }
  }

  /**
   * Find a node by route.
   */
  function findByRoute(route: string): NavigationNodeWithPath | null {
    for (const node of flatNodes.value) {
      if (node.to === route) {
        return node
      }
    }
    return null
  }

  /**
   * Return a node's parent path.
   */
  function getParentPath(path: string): string | null {
    const lastDot = path.lastIndexOf('.')
    if (lastDot === -1) {
      return null
    }
    return path.substring(0, lastDot)
  }

  /**
   * Return every ancestor path for a node.
   */
  function getAllParentPaths(path: string): string[] {
    const parents: string[] = []
    let current = path

    while (true) {
      const parent = getParentPath(current)
      if (parent === null) break
      parents.unshift(parent)
      current = parent
    }

    return parents
  }

  /**
   * Return whether a node is visible according to its predicate and privileges.
   */
  function isVisible(node: NavigationNode): boolean {
    // Check privileges first.
    if (!hasRequiredPrivileges(node)) {
      return false
    }

    // Check the custom visibility predicate.
    if (typeof node.visible === 'function') {
      return node.visible()
    }
    return node.visible !== false
  }

  /**
   * Return a badge value.
   */
  function getBadgeValue(node: NavigationNode): string | null {
    if (!node.badge) return null
    if (typeof node.badge === 'function') {
      return node.badge()
    }
    return node.badge
  }

  return {
    // State
    isLoading,
    loadError,

    // Arbres
    allTrees,

    // Methods
    getTreeByRoot,
    getSortedNodes,
    getChildren,
    findByPath,
    findByRoute,
    getParentPath,
    getAllParentPaths,
    isVisible,
    getBadgeValue,
    flatNodes
  }
}

// ============ Helpers ============

/**
 * Flatten the navigation tree into a list.
 */
function flattenTree(
  tree: NavigationTree,
  parentPath: string,
  depth: number
): NavigationNodeWithPath[] {
  const result: NavigationNodeWithPath[] = []

  for (const [key, node] of Object.entries(tree)) {
    const path = parentPath ? `${parentPath}.${key}` : key

    result.push({
      ...node,
      key,
      path,
      depth,
      childrenKeys: node.children ? Object.keys(node.children) : undefined
    })

    if (node.children) {
      result.push(...flattenTree(node.children, path, depth + 1))
    }
  }

  return result
}
