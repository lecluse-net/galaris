<template>
  <div class="left-menu" :class="{ 'mini': mini }">
    <q-list>
      <LeftMenuItems
        :tree="effectiveTree"
        parent-path=""
        :depth="0"
        :mini="mini"
      />
    </q-list>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { NavigationTree, NavigationNodeWithPath } from '../'
import { useNavigation, useNavigationStore } from '../'
import LeftMenuItems from './LeftMenuItems.vue'

interface Props {
  tree?: NavigationTree
  rootKey?: string
  mini?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  tree: undefined,
  rootKey: undefined,
  mini: false
})

const route = useRoute()
const store = useNavigationStore()
const { getTreeByRoot, getAllParentPaths } = useNavigation()

const effectiveTree = computed<NavigationTree>(() => {
  if (props.tree) return props.tree
  if (props.rootKey) return getTreeByRoot(props.rootKey)
  return {}
})

// Auto-expand parents of active route
watch(() => route.path, (path) => {
  // Find node with matching route
  const findNode = (tree: NavigationTree, parentPath: string): NavigationNodeWithPath | null => {
    for (const [key, node] of Object.entries(tree)) {
      const currentPath = parentPath ? `${parentPath}.${key}` : key
      if (node.to === path) {
        return { ...node, key, path: currentPath, depth: parentPath ? parentPath.split('.').length : 0 }
      }
      if (node.children) {
        const found = findNode(node.children, currentPath)
        if (found) return found
      }
    }
    return null
  }

  const activeNode = findNode(effectiveTree.value, '')
  if (activeNode) {
    store.setActiveNode(activeNode.path)
    const parents = getAllParentPaths(activeNode.path)
    parents.forEach(p => store.expand(p))
  }
}, { immediate: true })
</script>

<style scoped>
.left-menu {
  height: 100%;
  overflow-y: auto;
}
</style>
