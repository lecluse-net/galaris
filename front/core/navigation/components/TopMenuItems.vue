<template>
  <template v-for="child in sortedChildren" :key="child.path">
    <!-- Node with a nested submenu -->
    <template v-if="hasVisibleChildren(child)">
      <q-item
        clickable
        class="menu-item-with-children"
      >
        <!-- The submenu caption already displays the description. -->
        <q-item-section avatar v-if="child.icon">
          <q-icon :name="child.icon" size="xs" />
        </q-item-section>
        <q-item-section>
          <q-item-label>{{ $te(child.label ?? child.key) ? $t(child.label ?? child.key) : child.label }}</q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-icon name="chevron_right" size="xs" />
        </q-item-section>

        <q-menu anchor="top end" self="top start">
          <q-list>
            <TopMenuItems
              :children="child.children"
              :parent-path="child.path"
              :depth="depth + 1"
            />
          </q-list>
        </q-menu>
      </q-item>
    </template>

    <!-- Leaf node -->
    <q-item
      v-else
      clickable
      :to="child.to"
      :href="child.href"
      v-close-popup
      v-ripple
      :class="{ 'bg-primary text-white': isNodeActive(child) }"
    >
      <!-- The caption already displays the description. -->
      <q-item-section avatar v-if="child.icon">
        <q-icon :name="child.icon" size="xs" />
      </q-item-section>
      <q-item-section>
        <q-item-label>{{ $te(child.label ?? child.key) ? $t(child.label ?? child.key) : child.label }}</q-item-label>
        <q-item-label caption v-if="child.description">
          {{ $te(child.description) ? $t(child.description) : child.description }}
        </q-item-label>
      </q-item-section>
    </q-item>
  </template>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import type { NavigationTree, NavigationNodeWithPath } from '../'
import { useNavigation } from '../'

interface Props {
  children?: NavigationTree
  parentPath: string
  depth: number
}

const props = defineProps<Props>()
const route = useRoute()
const { isVisible } = useNavigation()

const sortedChildren = computed<NavigationNodeWithPath[]>(() => {
  if (!props.children) return []

  return Object.entries(props.children)
    .map(([key, node]) => ({
      ...node,
      key,
      path: props.parentPath ? `${props.parentPath}.${key}` : key,
      depth: props.depth,
      childrenKeys: node.children ? Object.keys(node.children) : undefined
    }))
    .filter(node => isVisible(node))
    .sort((a, b) => (a.order ?? 99) - (b.order ?? 99))
})

function isNodeActive(node: NavigationNodeWithPath): boolean {
  if (!node.to) return false
  return route.path === node.to
}

function hasVisibleChildren(node: NavigationNodeWithPath): boolean {
  if (!node.children || Object.keys(node.children).length === 0) return false
  return Object.values(node.children).some(child => isVisible(child))
}
</script>

<style scoped>
.menu-item-with-children {
  position: relative;
}
</style>
