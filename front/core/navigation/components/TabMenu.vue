<template>
  <q-tabs
    v-if="sortedNodes.length > 0"
    :align="align"
    class="tab-menu"
    :dense="dense"
    :vertical="vertical"
    no-caps
  >
    <q-route-tab
      v-for="node in sortedNodes"
      :key="node.path"
      :icon="node.icon"
      :label="node.label"
      :to="node.to"
      :exact="exact"
      :class="getTabClass(node)"
    />
  </q-tabs>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { NavigationTree, NavigationNodeWithPath } from '../'
import { useNavigation } from '../'

interface Props {
  /** Navigation tree to display; uses rootKey when omitted. */
  tree?: NavigationTree

  /** Root key of the displayed tree, for example 'settings'. */
  rootKey?: string

  /** Tab alignment. */
  align?: 'left' | 'center' | 'right' | 'justify'

  /** Mode dense */
  dense?: boolean

  /** Orientation verticale */
  vertical?: boolean

  /** Whether routes require exact matches. */
  exact?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  tree: undefined,
  rootKey: undefined,
  align: 'left',
  dense: false,
  vertical: false,
  exact: false
})

const { getTreeByRoot, isVisible } = useNavigation()

/** Effective displayed tree. */
const effectiveTree = computed<NavigationTree>(() => {
  if (props.tree) {
    return props.tree
  }
  if (props.rootKey) {
    return getTreeByRoot(props.rootKey)
  }
  return {}
})

/** Sorted and filtered nodes that have a route. */
const sortedNodes = computed<NavigationNodeWithPath[]>(() => {
  const entries = Object.entries(effectiveTree.value)
  const nodes = entries
    .map(([key, node]) => ({
      ...node,
      key,
      path: key,
      depth: 0,
      childrenKeys: node.children ? Object.keys(node.children) : undefined
    }))
    .filter(node => node.to) // Only nodes with a route.
    .sort((a, b) => (a.order ?? 99) - (b.order ?? 99))

  return nodes.filter(node => isVisible(node))
})

/** Tab CSS class. */
function getTabClass(node: NavigationNodeWithPath): string {
  const classes: string[] = []
  if (node.class) {
    classes.push(node.class)
  }
  return classes.join(' ')
}
</script>

<style scoped>
.tab-menu {
  width: 100%;
}
</style>
