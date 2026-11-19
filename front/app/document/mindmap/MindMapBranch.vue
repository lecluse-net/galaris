<template>
  <li
    class="mindmap-branch"
    :data-mindmap-node="node.id"
    :data-level="Math.min(level, 3)"
    role="treeitem"
    :aria-label="label"
    :aria-selected="selected.has(node.id)"
    :aria-expanded="branches.length ? !folded.has(node.id) : undefined"
    :tabindex="focused === node.id ? 0 : -1"
  >
    <slot :node="node" :label="label" :has-children="branches.length > 0" :closed="folded.has(node.id)" />
    <ul v-if="branches.length && !folded.has(node.id)" class="mindmap-children" role="group">
      <MindMapBranch
        v-for="child in branches" :key="child.id" :node="child" :children="children"
        :selected="selected" :focused="focused" :folded="folded" :level="level + 1"
      >
        <template #default="branch"><slot v-bind="branch" /></template>
      </MindMapBranch>
    </ul>
  </li>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { mindMapNodeLabel, type MindMapNode } from './model'

const props = defineProps<{
  node: MindMapNode
  children: Map<string | null, MindMapNode[]>
  selected: ReadonlySet<string>
  focused: string
  folded: ReadonlySet<string>
  level: number
  documentTitle?: string
}>()
defineSlots<{ default: (branch: { node: MindMapNode; label: string; hasChildren: boolean; closed: boolean }) => unknown }>()
const { t } = useI18n()
const branches = computed(() => props.children.get(props.node.id) ?? [])
const label = computed(() => mindMapNodeLabel(props.node, props.documentTitle, t('documents.mindmap.untitled')))
</script>

<style scoped src="./branch.css" />
