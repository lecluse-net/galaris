<template>
  <q-dialog :model-value="open" @update:model-value="!$event && close()">
    <q-card class="galaris-detail-dialog galaris-dialog-card dataset-dialog">
      <DialogHeader :title="resolvedTitle || title || t('datasets.editor')" icon="data_object" :close-label="t('datasets.close')" />
      <q-separator />
      <div class="galaris-dialog-body">
        <DatasetEditor v-if="open" :id="id" ref="editor" @loaded="resolvedTitle = $event.title"
          @updated="updated" @deleted="emit('deleted', $event)" />
      </div>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { nextTick, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import DatasetEditor from './DatasetEditor.vue'
import type { Dataset } from '../types'
import { DialogHeader } from '@/core/util'

defineProps<{ id: string; title?: string }>()
const emit = defineEmits<{ close: []; updated: [dataset: Dataset]; deleted: [id: string] }>()
const { t } = useI18n(), open = ref(true), resolvedTitle = ref('')
const editor = useTemplateRef<InstanceType<typeof DatasetEditor>>('editor')
let closing = false
async function close(): Promise<void> {
  if (closing) return
  closing = true
  try {
    if (editor.value && !await editor.value.canLeave()) return
    open.value = false
    await nextTick()
    emit('close')
  } finally { closing = false }
}
function updated(dataset: Dataset): void { resolvedTitle.value = dataset.title; emit('updated', dataset) }
function canLeave(): boolean | Promise<boolean> { return editor.value?.canLeave() ?? true }
defineExpose({ canLeave })
</script>
<style scoped>
.dataset-dialog { width: 1100px; height: calc(100dvh - 32px); }
</style>
