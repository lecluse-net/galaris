<template>
  <WorkingDocumentDialog ref="dialog" v-model="open" :document-id="documentId" :agent-id="agentId"
    :title="title" :editable="editable" card-class="conversation-document-dialog"
    @loaded="emit('changed', $event)" @updated="emit('changed', $event)"
    @unavailable="emit('unavailable', $event)" @deleted="emit('deleted', $event)" />
</template>
<script setup lang="ts">
import { useTemplateRef } from 'vue'
import { WorkingDocumentDialog, type WorkingDocumentSnapshot } from '@/core/util'

const open = defineModel<boolean>({ required: true })
const { documentId, agentId, title, editable = false } = defineProps<{
  documentId: string | null; agentId: number | null; title: string; editable?: boolean
}>()
const emit = defineEmits<{
  changed: [document: WorkingDocumentSnapshot]; unavailable: [id: string]; deleted: [id: string]
}>()
const dialog = useTemplateRef<InstanceType<typeof WorkingDocumentDialog>>('dialog')
async function flush(): Promise<boolean> { return await dialog.value?.flush() ?? true }
defineExpose({ flush })
</script>
