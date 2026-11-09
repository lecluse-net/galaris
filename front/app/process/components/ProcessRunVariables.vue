<template>
  <section :aria-label="t('nativeProcesses.variables.title')">
    <div class="text-subtitle2 text-weight-bold q-mb-sm">{{ t('nativeProcesses.variables.title') }}</div>
    <div v-if="!rows.length" class="text-body2">{{ t('nativeProcesses.variables.empty') }}</div>
    <div v-else class="resource-preview-grid">
      <div v-for="row in rows" :key="row.name" class="run-variable" :aria-label="row.name">
        <template v-if="resource(row)">
          <ResourceAttachments v-if="resources[row.name]" :key="`${runId}:${agentId}:${row.name}:${row.value}`"
            :resource-id="`${runId}:${row.name}`" :agent-id="agentId" :attachments="[resources[row.name]!]"
            :resource-source="source(row.name)" :show-heading="false" compact>
            <template #item-title>{{ title(row) }}</template>
            <template #item-description="{ attachment }"><span>{{ attachment.name }}</span> · {{ typeLabel(row.type) }}</template>
          </ResourceAttachments>
          <ResourcePreviewBlock v-else-if="!errors.has(row.name)" :title="title(row)" :subtitle="typeLabel(row.type)"
            :icon="icon(row.type)" :open-label="row.name" disabled>
            <template #description><q-skeleton type="text" /></template>
          </ResourcePreviewBlock>
          <ResourcePreviewBlock v-else :title="title(row)" :subtitle="typeLabel(row.type)" icon="error_outline"
            :description="t('documents.attachmentError')" :open-label="t('processes.refresh')" @open="loadResources" />
        </template>
        <ResourcePreviewBlock v-else :title="title(row)" :subtitle="typeLabel(row.type)" :icon="icon(row.type)"
          :open-label="row.name" :disabled="!row.initialized" @open="selected = row">
          <template #description><span class="run-variable-value">{{ display(row) }}</span></template>
        </ResourcePreviewBlock>
        <div v-if="row.description" class="text-caption q-mt-xs">{{ row.description }}</div>
        <q-btn v-if="editableNames?.includes(row.name)" outline dense color="primary" icon="edit" class="q-mt-xs"
          :label="t('nativeProcesses.inputs.editAction')" :aria-label="t('nativeProcesses.inputs.edit', { name: row.label || row.name })" @click="emit('edit', row.name)" />
      </div>
    </div>
    <q-dialog :model-value="Boolean(selected)" @update:model-value="selected = null">
      <q-card class="galaris-dialog-card run-variable-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6 ellipsis">{{ selected?.name }} · {{ selected ? typeLabel(selected.type) : '' }}</div>
          <q-space /><q-btn flat round dense icon="close" :aria-label="t('common.close')" @click="selected = null" />
        </q-card-section>
        <q-card-section><pre class="run-variable-full">{{ selected ? display(selected) : '' }}</pre></q-card-section>
      </q-card>
    </q-dialog>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ResourceAttachments, ResourcePreviewBlock, type ResourceAttachment } from '@/core/util'
import { nativeProcessService as service, type ProcessVariable } from '../services/nativeProcessService'

const props = defineProps<{ variables: ProcessVariable[]; data: Record<string, unknown>; runId?: string; agentId?: number | null; editableNames?: string[] }>()
const emit = defineEmits<{ edit: [name: string] }>()
const { t } = useI18n()
const rows = computed(() => props.variables.map(variable => ({ ...variable,
  initialized: Object.hasOwn(props.data, variable.name), value: plainValue(props.data[variable.name]),
})))
type Row = typeof rows.value[number]
function title(row: Row): string { return row.label ? `${row.label} · ${row.name}` : row.name }
const resources = shallowRef<Record<string, ResourceAttachment>>({})
const errors = shallowRef(new Set<string>())
const selected = shallowRef<Row | null>(null)
let controller: AbortController | undefined
function plainValue(envelope: unknown): unknown {
  if (!envelope || typeof envelope !== 'object' || !('value' in envelope)) return envelope
  const { value } = envelope
  if (!value || typeof value !== 'object') return value
  return Array.isArray(value) ? value.map(plainValue)
    : Object.fromEntries(Object.entries(value).map(([name, child]) => [name, plainValue(child)]))
}
function resource(row: Row): boolean { return ['File', 'Document'].includes(row.type) && typeof row.value === 'string' && row.initialized }
function typeLabel(type: string): string { return t(`nativeProcesses.variables.types.${type}`) }
function display(row: Row): string {
  if (!row.initialized) return t('nativeProcesses.variables.unset')
  if (row.value === '') return '""'
  return typeof row.value === 'string' ? row.value : JSON.stringify(row.value, null, 2) ?? ''
}
function icon(type: string): string { return ({ int: 'numbers', float: 'numbers', bool: 'toggle_on', date: 'event', datetime: 'event', string: 'text_fields' } as Record<string, string>)[type] ?? 'data_object' }
function source(name: string) {
  const id = props.runId!, agent = props.agentId
  return {
    content: (_attachment: ResourceAttachment, preview: boolean, signal?: AbortSignal) => service.variableContent(id, name, preview, agent, signal),
    thumbnail: (_attachment: ResourceAttachment, signal?: AbortSignal) => service.variableThumbnail(id, name, agent, signal),
  }
}
async function loadResources(): Promise<void> {
  controller?.abort()
  const current = new AbortController(); controller = current
  resources.value = {}; errors.value = new Set(); selected.value = null
  const pending = rows.value.filter(resource), id = props.runId, agent = props.agentId
  if (!id) { errors.value = new Set(pending.map(row => row.name)); return }
  async function worker() {
    while (pending.length && !current.signal.aborted) {
      const row = pending.shift()!
      try {
        const info = await service.variableResource(id!, row.name, agent, current.signal)
        if (!current.signal.aborted) resources.value = { ...resources.value, [row.name]: { ...info, id: row.name } }
      } catch {
        if (!current.signal.aborted) errors.value = new Set([...errors.value, row.name])
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, pending.length) }, worker))
}
watch(() => JSON.stringify([props.runId, props.agentId, rows.value]), loadResources, { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>
<style scoped>
.run-variable { min-width: 0; display: flex; flex-direction: column; align-items: stretch; }
.run-variable > :is(.resource-preview-block, .document-attachments) { flex: 1; }
.run-variable :deep(.document-attachments__list) { height: 100%; }
.run-variable-value { overflow: hidden; overflow-wrap: anywhere; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.run-variable-full { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
.run-variable-dialog { width: 640px; max-width: 95vw; }
</style>
