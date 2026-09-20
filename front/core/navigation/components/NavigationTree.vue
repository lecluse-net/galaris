<template>
  <div class="navigation-tree">
    <LeftMenu :tree="effectiveTree" :max-depth="maxDepth" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { NavigationTree } from '../'
import LeftMenu from './LeftMenu.vue'

interface Props {
  /** Navigation tree to display. */
  tree?: NavigationTree

  /** Maximum displayed depth; undefined means unlimited. */
  maxDepth?: number
}

const props = withDefaults(defineProps<Props>(), {
  tree: undefined,
  maxDepth: undefined
})

/** Effective tree, empty when none is provided. */
const effectiveTree = computed<NavigationTree>(() => {
  return props.tree || {}
})
</script>

<style scoped>
.navigation-tree {
  width: 100%;
}
</style>
