/**
 * Pinia store for tree navigation, expanded nodes, and the active node.
 */

import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useNavigationStore = defineStore('navigation', () => {
  // State

  /** Expanded nodes, using complete paths such as 'administration.settings'. */
  const expandedNodes = ref<Set<string>>(new Set())

  /** Active node path for the current route. */
  const activeNodePath = ref<string | null>(null)


  // ============ Getters ============

  /** Return whether a node is expanded. */
  const isExpanded = computed(() => (path: string) => expandedNodes.value.has(path))

  /** Return whether a node is active. */
  const isActive = computed(() => (path: string) => activeNodePath.value === path)

  /** Return the active node path. */
  const activePath = computed(() => activeNodePath.value)

  // ============ Actions ============

  /**
   * Toggle a node.
   */
  function toggleExpanded(path: string) {
    if (expandedNodes.value.has(path)) {
      expandedNodes.value.delete(path)
    } else {
      expandedNodes.value.add(path)
    }
  }

  /**
   * Expand a node.
   */
  function expand(path: string) {
    expandedNodes.value.add(path)
  }

  /**
   * Collapse a node.
   */
  function collapse(path: string) {
    expandedNodes.value.delete(path)
  }

  /**
   * Expand every ancestor up to the root.
   */
  function expandParents(nodePath: string) {
    const parents = getParentPaths(nodePath)
    parents.forEach(path => expandedNodes.value.add(path))
  }

  /**
   * Set the active node.
   */
  function setActiveNode(path: string | null) {
    activeNodePath.value = path
  }


  /**
   * Reset expanded state.
   */
  function resetExpansion() {
    expandedNodes.value.clear()
  }

  // ============ Helpers ============

  /**
   * Return every ancestor path.
   * Example: 'administration.settings.general' => ['administration', 'administration.settings']
   */
  function getParentPaths(nodePath: string): string[] {
    const parents: string[] = []
    const parts = nodePath.split('.')

    // Build ancestor paths incrementally.
    let currentPath = ''
    for (let i = 0; i < parts.length - 1; i++) {
      currentPath = currentPath ? `${currentPath}.${parts[i]}` : parts[i]
      parents.push(currentPath)
    }

    return parents
  }

  /**
   * Return the direct parent path.
   * Example: 'administration.settings.general' => 'administration.settings'
   */
  function getParentPath(nodePath: string): string | null {
    const lastDot = nodePath.lastIndexOf('.')
    if (lastDot === -1) {
      return null
    }
    return nodePath.substring(0, lastDot)
  }

  /**
   * Return the final key in a path.
   * Example: 'administration.settings' => 'settings'
   */
  function getNodeKey(nodePath: string): string {
    const lastDot = nodePath.lastIndexOf('.')
    if (lastDot === -1) {
      return nodePath
    }
    return nodePath.substring(lastDot + 1)
  }

  // ============ Exports ============

  return {
    // State
    expandedNodes,
    activeNodePath,

    // Getters
    isExpanded,
    isActive,
    activePath,

    // Actions
    toggleExpanded,
    expand,
    collapse,
    expandParents,
    setActiveNode,
    resetExpansion,

    // Helpers
    getParentPaths,
    getParentPath,
    getNodeKey
  }
})
