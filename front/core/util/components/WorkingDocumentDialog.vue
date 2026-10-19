<template>
  <component :is="workingDocumentDialog" v-if="workingDocumentDialog" ref="dialog" v-model="open" v-bind="props"
    @loaded="emit('loaded', $event)" @updated="emit('updated', $event)"
    @unavailable="emit('unavailable', $event)" @deleted="emit('deleted', $event)" />
</template>
<script setup lang="ts">
import { useTemplateRef } from 'vue'
import { workingDocumentDialog, type WorkingDocumentSnapshot } from '../workingDocumentEditor'

const open = defineModel<boolean>({ required: true })
const props = defineProps<{
  documentId: string | null
  agentId: number | null
  title?: string
  editable?: boolean
  cardClass?: string
}>()
const emit = defineEmits<{
  loaded: [document: WorkingDocumentSnapshot]
  updated: [document: WorkingDocumentSnapshot]
  unavailable: [id: string]
  deleted: [id: string]
}>()
const dialog = useTemplateRef<{ flush: () => Promise<boolean> }>('dialog')
async function flush(): Promise<boolean> { return await dialog.value?.flush() ?? true }
defineExpose({ flush })
</script>
