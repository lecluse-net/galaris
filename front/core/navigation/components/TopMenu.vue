<template>
  <div v-if="sortedNodes.length > 0" class="top-menu row items-center">
    <template v-for="node in sortedNodes" :key="node.path">
      <!-- Node with submenu -->
      <template v-if="hasVisibleChildren(node)">
        <div class="menu-item-with-children row items-center" :class="{ 'active-item': isNodeActive(node) }">
          <!-- Left side: navigation. -->
          <q-btn
            v-if="node.to"
            flat
            no-caps
            :to="node.to"
            class="menu-item-main"
          >
            <q-tooltip v-if="node.description">{{ node.description }}</q-tooltip>
            <div class="row items-center no-wrap">
              <q-icon v-if="node.icon" :name="node.icon" class="q-mr-sm" />
              <span>{{ node.label }}</span>
            </div>
          </q-btn>

          <!-- Left side: label without a route -->
          <div v-else class="menu-item-main row items-center no-wrap q-px-md">
            <q-tooltip v-if="node.description">{{ node.description }}</q-tooltip>
            <q-icon v-if="node.icon" :name="node.icon" class="q-mr-sm" />
            <span>{{ node.label }}</span>
          </div>

          <!-- Right side: dropdown button. -->
          <q-btn
            flat
            dense
            icon="expand_more"
            class="expand-btn"
          >
            <q-menu>
              <q-list>
                <TopMenuItems
                  :children="node.children"
                  :parent-path="node.path"
                  :depth="1"
                />
              </q-list>
            </q-menu>
          </q-btn>
        </div>
      </template>

      <!-- Leaf node -->
      <q-btn
        v-else
        flat
        no-caps
        :to="node.to"
        :class="['q-mx-xs', { 'active-item': isNodeActive(node) }]"
      >
        <q-tooltip v-if="node.description">{{ node.description }}</q-tooltip>
        <div class="row items-center no-wrap">
          <q-icon v-if="node.icon" :name="node.icon" class="q-mr-sm" />
          <span>{{ node.label }}</span>
        </div>
      </q-btn>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import type { NavigationTree, NavigationNodeWithPath } from '../'
import { useNavigation } from '../'
import TopMenuItems from './TopMenuItems.vue'

interface Props {
  /** Navigation tree to display; uses rootKey when omitted. */
  tree?: NavigationTree

  /** Root key of the displayed tree, for example 'quickaccess'. */
  rootKey?: string
}

const props = withDefaults(defineProps<Props>(), {
  tree: undefined,
  rootKey: undefined
})

const route = useRoute()
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

/** Sorted and filtered nodes. */
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
    .sort((a, b) => (a.order ?? 99) - (b.order ?? 99))

  return nodes.filter(node => isVisible(node))
})

/** Return whether a node is active. */
function isNodeActive(node: NavigationNodeWithPath): boolean {
  if (!node.to) return false
  return route.path === node.to
}

/** Return whether a node has visible children. */
function hasVisibleChildren(node: NavigationNodeWithPath): boolean {
  if (!node.children || Object.keys(node.children).length === 0) {
    return false
  }
  return Object.values(node.children).some(child => isVisible(child))
}
</script>

<style scoped>
.top-menu {
  min-height: 40px;
}

.menu-item-with-children {
  display: flex;
  align-items: center;
  margin: 0 4px;
  border-radius: 4px;
}

.menu-item-main {
  flex: 1;
  min-width: 0;
}

.expand-btn {
  border-radius: 0 4px 4px 0;
}

.active-item {
  background-color: rgba(255, 255, 255, 0.15);
}

:deep(.q-menu) {
  min-width: 200px;
}
</style>
