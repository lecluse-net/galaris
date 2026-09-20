<template>
  <TopMenu :root-key="rootKey" :tree="tree" />
</template>

<script setup lang="ts">
import type { NavigationTree } from '../'
import TopMenu from './TopMenu.vue'

interface Props {
  /** Root key of the displayed tree, for example 'quickaccess'. */
  rootKey?: string

  /** Navigation tree to display directly instead of rootKey. */
  tree?: NavigationTree
}

const props = withDefaults(defineProps<Props>(), {
  rootKey: undefined,
  tree: undefined
})
</script>
