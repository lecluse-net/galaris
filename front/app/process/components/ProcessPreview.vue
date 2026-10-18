<template>
  <section ref="root" class="process-preview" :class="{ 'process-preview--inline': inline }">
    <div v-if="loading" class="q-pa-md" role="status"><q-spinner color="primary" /></div>
    <q-banner v-else-if="error" role="alert">{{ t('nativeProcesses.resources.unavailable') }}
      <template #action><q-btn outline :label="t('common.retry')" @click="load" /></template>
    </q-banner>
    <template v-else-if="preview">
      <div v-if="!inline" class="q-pa-md">
        <q-badge outline>{{ t('nativeProcesses.readOnly') }}</q-badge>
        <p v-if="preview.description" class="q-mt-sm">{{ preview.description }}</p>
      </div>
      <BpmnCanvas :model-value="graph" readonly auto-fit :show-guide="!inline" :selected="selected" @select="selected = $event" @dismiss="selected = null">
        <template v-if="inline" #toolbar-leading>
          <q-btn outline round dense icon="open_in_full" :aria-label="t('nativeProcesses.resources.open')" @click="open = true" />
        </template>
        <template #inspector>
          <div v-if="selectedNode" class="q-pa-sm">
            <div class="text-subtitle2">{{ selectedNode.title }}</div>
            <p v-if="selectedNode.config.prompt">{{ selectedNode.config.prompt }}</p>
            <q-btn v-if="selectedNode.body" outline :label="t('nativeProcesses.openBody')" @click="path.push(selectedNode.id); selected = null" />
          </div>
        </template>
      </BpmnCanvas>
      <q-btn v-if="path.length" outline icon="arrow_back" :label="t('nativeProcesses.resources.parentDiagram')" @click="path.pop(); selected = null" />
    </template>
    <ResourceDetailDialog v-if="open && target" :target="target" @close="open = false" />
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ResourceDetailDialog, captureElementRendering } from '@/core/util'
import BpmnCanvas from './BpmnCanvas.vue'
import { processResourceTarget } from '../contracts'
import { processResourceService, type ProcessResourcePreview } from '../services/processResourceService'
const { uri, agentId = null, inline = false } = defineProps<{ uri: string; agentId?: number | null; inline?: boolean }>()
const emit = defineEmits<{ loaded: [preview: ProcessResourcePreview] }>()
const { t } = useI18n()
const preview = shallowRef<ProcessResourcePreview | null>(null), error = ref(false), loading = ref(false), open = ref(false)
const selected = ref<string | null>(null), path = ref<string[]>([])
const graph = computed(() => {
  let value = preview.value!.graph
  for (const id of path.value) { const body = value.nodes.find(node => node.id === id)?.body; if (body) value = body }
  return value
})
const selectedNode = computed(() => preview.value ? graph.value.nodes.find(node => node.id === selected.value) : null)
const target = computed(() => processResourceTarget(uri, preview.value?.title ?? '', agentId))
const root = useTemplateRef('root')
async function capture(signal: AbortSignal): Promise<string> {
  const board = root.value?.querySelector<HTMLElement>('.diagram-board')
  if (!board || loading.value || error.value) throw new Error('Process rendering unavailable')
  return captureElementRendering(board, signal)
}
defineExpose({ capture })
let request: AbortController | undefined
async function load(): Promise<void> {
  request?.abort(); const controller = new AbortController(); request = controller
  preview.value = null; error.value = false; loading.value = true; selected.value = null; path.value = []; open.value = false
  try {
    const value = await processResourceService.preview(uri, agentId, controller.signal)
    if (!controller.signal.aborted) { preview.value = value; emit('loaded', value) }
  }
  catch { if (!controller.signal.aborted) error.value = true }
  finally { if (!controller.signal.aborted) loading.value = false }
}
watch(() => [uri, agentId], load, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>
<style scoped>
.process-preview { min-width: 0; }
.process-preview--inline :deep(.diagram-editor) { position: relative; }
.process-preview--inline :deep(.diagram-toolbar) { position: absolute; top: 4px; right: 4px; z-index: 4; padding: 4px; border: 0; background: var(--solaire-gray-light); opacity: 0; pointer-events: none; transition: opacity .15s; }
.process-preview--inline:hover :deep(.diagram-toolbar), .process-preview--inline:focus-within :deep(.diagram-toolbar) { opacity: 1; pointer-events: auto; }
.process-preview--inline :deep(.bpmn-scroll) { height: 320px; min-height: 0; }
.body--dark .process-preview--inline :deep(.diagram-toolbar) { background: var(--solaire-gray-dark); }
.process-preview--inline :deep(.diagram-editor.fullscreen .bpmn-scroll) { height: calc(100dvh - 70px); }
.process-preview--inline :deep(.diagram-editor.fullscreen .diagram-toolbar) { opacity: 1; pointer-events: auto; }
@media (hover: none) { .process-preview--inline :deep(.diagram-toolbar) { opacity: 1; pointer-events: auto; } }
</style>
