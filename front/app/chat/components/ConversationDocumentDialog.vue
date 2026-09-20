<template>
  <q-dialog allow-focus-outside v-model="open" @before-hide="flushDocument">
    <q-card class="conversation-document-dialog galaris-detail-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <DocumentIcon v-if="documentId" :document-id="documentId" :title="title" size="24px" class="q-mr-sm" />
        <div class="text-h6 ellipsis">{{ title || t('chat.workingDocument') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <div class="conversation-document-editor">
        <WorkingDocumentEditor
          v-if="documentId"
          ref="workingDocumentEditor"
          :key="`${agentId}:${documentId}`"
          :document-id="documentId"
          :agent-id="agentId"
          :editable="editable"
          content-min-height="min(42vh, 440px)"
          content-max-height="52vh"
          @loaded="emit('changed', $event)"
          @updated="emit('changed', $event)"
          @unavailable="emit('unavailable', $event)"
        />
      </div>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon } from '@/core/util'
import { useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { WorkingDocumentEditor } from '@/core/util'
import type { WorkingDocumentSnapshot } from '@/core/util'

const open = defineModel<boolean>({ required: true })
const { documentId, agentId, title, editable = false } = defineProps<{
  documentId: string | null
  agentId: number | null
  title: string
  editable?: boolean
}>()
const emit = defineEmits<{
  changed: [document: WorkingDocumentSnapshot]
  unavailable: [documentId: string]
}>()

const { t } = useI18n()
const workingDocumentEditor = useTemplateRef<InstanceType<typeof WorkingDocumentEditor>>(
  'workingDocumentEditor',
)

function flushDocument(): void {
  void workingDocumentEditor.value?.flush()
}
async function flush(): Promise<boolean> { return await workingDocumentEditor.value?.flush() ?? true }
defineExpose({ flush })
</script>

<style scoped>
.conversation-document-dialog { display: flex; width: min(94vw, 980px); max-width: 980px; min-height: 420px; max-height: calc(100vh - 32px); flex-direction: column; }
.conversation-document-editor { min-height: 0; flex: 1 1 auto; overflow-y: auto; }
</style>
