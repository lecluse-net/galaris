<template>
  <section class="chat-document-pane" :aria-label="t('chat.workingDocument')">
    <q-toolbar class="chat-document-toolbar">
      <DocumentIcon :document-id="document.id" :title="title" class="q-mr-sm" />
      <q-toolbar-title class="text-body2 ellipsis">{{ title }}</q-toolbar-title>
      <slot name="actions" />
      <q-btn flat round dense icon="close" :aria-label="t('chat.closeWorkingDocument')" @click="close" />
    </q-toolbar>
    <div class="chat-document-content">
      <WorkingDocumentEditor ref="editor" :key="`${agentId}:${document.id}`" :document-id="document.id" :agent-id="agentId"
        :editable="editable" content-min-height="100px" @loaded="changed" @updated="changed" @unavailable="unavailable" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { WorkingDocumentIcon as DocumentIcon } from '@/core/util'
import { ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { WorkingDocumentEditor, type WorkingDocumentReference, type WorkingDocumentSnapshot } from '@/core/util'
const { document, agentId, editable } = defineProps<{ document: WorkingDocumentReference; agentId: number | null; editable: boolean }>()
const emit = defineEmits<{ close: []; available: [documentId: string]; unavailable: [] }>()
const { t } = useI18n()
const title = ref(document.title)
const editor = useTemplateRef<InstanceType<typeof WorkingDocumentEditor>>('editor')
async function flush(): Promise<boolean> { return await editor.value?.flush() ?? true }
async function close(): Promise<void> { if (await flush()) emit('close') }
defineExpose({ flush })
watch(() => document, value => { title.value = value.title })
function changed(value: WorkingDocumentSnapshot): void {
  if (value.id !== document.id) return
  title.value = value.title
  emit('available', value.id)
}
function unavailable(): void { title.value = t('chat.workingDocument'); emit('unavailable') }
</script>

<style scoped>
.chat-document-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; background: var(--chat-surface); }
.chat-document-toolbar { flex: 0 0 auto; flex-wrap: wrap; min-height: 36px; border-bottom: 1px solid var(--chat-border); }
.chat-document-content { flex: 1; min-height: 0; overflow: auto; }
</style>
