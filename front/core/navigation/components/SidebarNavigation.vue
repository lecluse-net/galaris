<template>
  <div class="sidebar-navigation">
    <!-- Optional titled header -->
    <div v-if="title" class="sidebar-header q-pa-sm">
      <q-item-label header class="text-grey-8">
        {{ title }}
      </q-item-label>
      <q-separator />
    </div>

    <!-- Left navigation tree. -->
    <LeftMenu :root-key="rootKey" :tree="tree" :max-depth="maxDepth" />
  </div>
</template>

<script setup lang="ts">
import type { NavigationTree } from '../'
import LeftMenu from './LeftMenu.vue'

interface Props {
  /** Root key of the displayed tree, for example 'administration'. */
  rootKey?: string

  /** Navigation tree to display directly instead of rootKey. */
  tree?: NavigationTree

  /** Optional menu title. */
  title?: string

  /** Maximum displayed depth. */
  maxDepth?: number
}

const props = withDefaults(defineProps<Props>(), {
  rootKey: undefined,
  tree: undefined,
  title: undefined,
  maxDepth: undefined
})
</script>

<style scoped>
.sidebar-navigation {
  height: 100%;
  overflow-y: auto;
}

.sidebar-header {
  display: flex;
  flex-direction: column;
}
</style>
