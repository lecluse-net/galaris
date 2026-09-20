<template>
  <component
    :is="workingDocumentEditor"
    v-if="workingDocumentEditor"
    ref="editor"
    :document-id="documentId"
    :agent-id="agentId"
    :editable="editable"
    :content-min-height="contentMinHeight"
    :content-max-height="contentMaxHeight"
    @loaded="forwardLoaded"
    @updated="forwardUpdated"
    @unavailable="forwardUnavailable"
  />
</template>

<script setup lang="ts">
import { useTemplateRef } from 'vue'
import {
  workingDocumentEditor,
  type WorkingDocumentSnapshot,
} from '../workingDocumentEditor'

withDefaults(defineProps<{
  documentId: string
  agentId: number | null
  editable?: boolean
  contentMinHeight?: string
  contentMaxHeight?: string
}>(), {
  editable: true,
  contentMinHeight: '520px',
})

const emit = defineEmits<{
  loaded: [document: WorkingDocumentSnapshot]
  updated: [document: WorkingDocumentSnapshot]
  unavailable: [documentId: string]
}>()

interface FlushableEditor {
  flush?: () => Promise<boolean>
}

const editor = useTemplateRef<FlushableEditor>('editor')

async function flush(): Promise<boolean> {
  return await editor.value?.flush?.() ?? true
}

defineExpose({ flush })

function isDocumentSnapshot(value: unknown): value is WorkingDocumentSnapshot {
  if (!value || typeof value !== 'object') return false
  const document = value as Partial<WorkingDocumentSnapshot>
  return typeof document.id === 'string'
    && typeof document.title === 'string'
    && typeof document.revision === 'number'
    && (document.updated_at === null || typeof document.updated_at === 'string')
    && typeof document.payload === 'object'
    && document.payload !== null
}

function forwardLoaded(value: unknown): void {
  if (isDocumentSnapshot(value)) emit('loaded', value)
}

function forwardUpdated(value: unknown): void {
  if (isDocumentSnapshot(value)) emit('updated', value)
}

function forwardUnavailable(value: unknown): void {
  if (typeof value === 'string') emit('unavailable', value)
}
</script>
