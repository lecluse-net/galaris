<template>
  <section class="chat-document-pane" :aria-label="t('chat.workingDocument')">
    <q-toolbar class="chat-document-toolbar">
      <DocumentIcon :document-id="document.id" :title="title" class="q-mr-sm" />
      <q-toolbar-title class="text-body2 ellipsis">{{ title }}</q-toolbar-title>
      <DocumentNavigationButtons class="q-mr-sm" :can-go-back="canGoBack" :can-go-forward="canGoForward" @back="emit('back')" @forward="emit('forward')" />
      <slot name="actions" />
      <q-btn flat round dense icon="close" :aria-label="t('chat.closeWorkingDocument')" @click="close"><q-tooltip>{{ t('chat.closeWorkingDocument') }}</q-tooltip></q-btn>
    </q-toolbar>
    <div class="chat-document-content">
      <WorkingDocumentEditor ref="editor" :key="`${agentId}:${document.id}`" :document-id="document.id" :agent-id="agentId"
        :initial-document="initialDocument"
        :editable="editable" content-min-height="100px" @loaded="changed" @updated="changed" @unavailable="unavailable" @deleted="deleted" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon } from '@/core/util'
import { ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DocumentNavigationButtons, WorkingDocumentEditor, type WorkingDocumentReference, type WorkingDocumentSnapshot } from '@/core/util'
const { document, agentId, editable, initialDocument = null, canGoBack = false, canGoForward = false } = defineProps<{
  document: WorkingDocumentReference; agentId: number | null; editable: boolean
  initialDocument?: WorkingDocumentSnapshot | null; canGoBack?: boolean; canGoForward?: boolean
}>()
const emit = defineEmits<{ close: []; available: [documentId: string]; unavailable: []; deleted: [documentId: string]; back: []; forward: [] }>()
const { t } = useI18n()
const title = ref(document.title)
const editor = useTemplateRef<InstanceType<typeof WorkingDocumentEditor>>('editor')
async function flush(): Promise<boolean> { return await editor.value?.flush() ?? true }
async function close(): Promise<void> { if (await flush()) emit('close') }
defineExpose({ flush, captureFocus: () => editor.value?.captureFocus() ?? null })
watch(() => document, value => { title.value = value.title })
function changed(value: WorkingDocumentSnapshot): void {
  if (value.id !== document.id) return
  title.value = value.title
  emit('available', value.id)
}
function unavailable(): void { title.value = t('chat.workingDocument'); emit('unavailable') }
function deleted(documentId: string): void {
  if (documentId === document.id) emit('deleted', documentId)
}
</script>

<style scoped>
.chat-document-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; background: var(--chat-surface); }
.chat-document-toolbar { flex: 0 0 auto; flex-wrap: wrap; min-height: 36px; border-bottom: 1px solid var(--chat-border); }
.chat-document-content { flex: 1; min-height: 0; overflow: auto; }
</style>
