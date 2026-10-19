<template>
  <q-dialog :model-value="open" @update:model-value="!$event && close()">
    <q-card class="galaris-detail-dialog galaris-dialog-card dataset-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="data_object" size="sm" class="q-mr-sm" />
        <div class="text-h6 ellipsis">{{ resolvedTitle || title || t('datasets.editor') }}</div><q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('datasets.close')" />
      </q-card-section>
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
</script>
<style scoped>
.dataset-dialog { width: 1100px; }
</style>
