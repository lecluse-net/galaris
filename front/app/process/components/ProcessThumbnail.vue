<template>
  <div ref="root" class="process-thumbnail process-diagram-theme" :aria-label="title" role="img">
    <svg v-if="preview" :viewBox="bounds" aria-hidden="true">
      <line v-for="flow in edges" :key="flow.id" :x1="flow.x1" :y1="flow.y1" :x2="flow.x2" :y2="flow.y2" class="edge" />
      <g v-for="node in graph?.nodes" :key="node.id" :transform="`translate(${node.x},${node.y})`">
        <rect width="180" height="72" :rx="['start', 'end'].includes(node.kind) ? 36 : 10" class="node process-diagram-node" :class="node.kind" />
        <text x="90" y="42" text-anchor="middle">{{ node.title.slice(0, 24) }}</text>
      </g>
    </svg>
    <q-icon v-else name="account_tree" size="48px" color="primary" />
    <q-badge v-if="run" class="process-thumbnail-run" color="primary"><q-icon name="play_arrow" size="20px" /><q-tooltip>{{ t('nativeProcesses.resources.run') }}</q-tooltip></q-badge>
  </div>
</template>
<script setup lang="ts">
import '../processDiagram.css'
import { computed, onBeforeUnmount, onMounted, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { queuePreview } from '@/core/util'
import { processResourceService, type ProcessResourcePreview } from '../services/processResourceService'
import { persistLayout } from '../graphEditing'
const { uri, agentId = null, title } = defineProps<{ uri: string; agentId?: number | null; title: string }>()
const { t } = useI18n()
const root = useTemplateRef<HTMLElement>('root')
const preview = shallowRef<ProcessResourcePreview | null>(null)
const run = computed(() => uri.startsWith('galaris://processes/runs/'))
const graph = computed(() => preview.value ? persistLayout(preview.value.graph) : null)
const bounds = computed(() => {
  const nodes = graph.value?.nodes ?? []
  const left = Math.min(0, ...nodes.map(node => node.x)) - 20, top = Math.min(0, ...nodes.map(node => node.y)) - 20
  return `${left} ${top} ${Math.max(200, ...nodes.map(node => node.x + 200)) - left} ${Math.max(100, ...nodes.map(node => node.y + 92)) - top}`
})
const edges = computed(() => (graph.value?.flows ?? []).flatMap(flow => {
  const start = graph.value?.nodes.find(node => node.id === flow.source), end = graph.value?.nodes.find(node => node.id === flow.target)
  return start && end ? [{ id: flow.id, x1: start.x + 180, y1: start.y + 36, x2: end.x, y2: end.y + 36 }] : []
}))
let observer: IntersectionObserver | undefined, request: AbortController | undefined, visible = false
function load(): void {
  request?.abort(); preview.value = null
  if (!visible) return
  const controller = new AbortController(); request = controller
  void queuePreview(() => processResourceService.preview(uri, agentId, controller.signal, true), controller.signal)
    .then(value => { if (!controller.signal.aborted) preview.value = value })
    .catch(() => { /* Opening remains available when the miniature is unavailable. */ })
}
watch(() => [uri, agentId], load)
onMounted(() => {
  observer = new IntersectionObserver(entries => {
    const next = entries.some(entry => entry.isIntersecting)
    if (next !== visible) { visible = next; load() }
  }, { rootMargin: '100px' })
  if (root.value) observer.observe(root.value)
})
onBeforeUnmount(() => { request?.abort(); observer?.disconnect() })
</script>
<style scoped>
.process-thumbnail { position: relative; width: 100%; height: 100%; min-height: 86px; display: grid; place-items: center; background: var(--diagram-lane); }
svg { width: 100%; height: 100%; }
.edge { stroke: var(--diagram-line); stroke-width: 1.8; }
.node { fill: var(--node-fill); stroke: var(--node-accent); stroke-width: var(--node-border-width); }
text { fill: var(--diagram-text); font-size: 15px; font-weight: 700; }
.process-thumbnail-run { position: absolute; bottom: 4px; right: 4px; }
</style>
