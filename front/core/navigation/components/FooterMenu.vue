<template>
  <div class="footer-menu bg-grey-8 text-grey-4 shadow-up-2" :class="{ 'mini': mini }">
    <q-toolbar :class="mini ? 'justify-center column' : 'justify-center'">
      <template v-for="node in sortedNodes" :key="node.path">
        <q-btn
          v-if="node.to"
          flat
          :to="node.to"
          :icon="node.icon"
          :label="mini ? undefined : translatedLabel(node.label)"
          :class="[isNodeActive(node) ? 'text-white' : 'text-grey-6', mini ? 'q-my-xs' : 'q-mx-sm']"
        >
          <q-tooltip v-if="mini">{{ translatedLabel(node.label) }}</q-tooltip>
        </q-btn>
        <q-btn
          v-else-if="node.href"
          flat
          :href="node.href"
          target="_blank"
          :icon="node.icon"
          :label="mini ? undefined : translatedLabel(node.label)"
          :class="[mini ? 'q-my-xs' : 'q-mx-sm', 'text-grey-4']"
        >
          <q-tooltip v-if="mini">{{ translatedLabel(node.label) }}</q-tooltip>
        </q-btn>
      </template>
    </q-toolbar>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { NavigationTree, NavigationNodeWithPath } from '../'
import { useNavigation } from '../'

interface Props {
  tree?: NavigationTree
  rootKey?: string
  mini?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  tree: undefined,
  rootKey: 'footer',
  mini: false
})

const route = useRoute()
const { getTreeByRoot, isVisible } = useNavigation()
const { t, te } = useI18n()

const effectiveTree = computed<NavigationTree>(() => {
  if (props.tree) return props.tree
  if (props.rootKey) return getTreeByRoot(props.rootKey)
  return {}
})

const sortedNodes = computed<NavigationNodeWithPath[]>(() => {
  const tree = effectiveTree.value
  if (!tree || Object.keys(tree).length === 0) return []

  return Object.entries(tree)
    .map(([key, node]) => ({
      ...node,
      key,
      path: key,
      depth: 0
    }))
    .filter(node => isVisible(node))
    .sort((a, b) => (a.order ?? 99) - (b.order ?? 99))
})

function isNodeActive(node: NavigationNodeWithPath): boolean {
  if (!node.to) return false
  return route.path === node.to
}

function translatedLabel(label: string = ''): string {
  return te(label) ? t(label) : label
}
</script>

<style scoped>
.footer-menu {
  min-height: 48px;
  flex-shrink: 0;
}

.footer-menu.mini {
  min-height: auto;
}

.footer-menu.mini :deep(.q-toolbar) {
  padding: 4px 0;
}
</style>
