<template>
  <q-dialog :model-value="mismatch !== null" @update:model-value="!$event && emit('cancel')">
    <q-card v-if="mismatch" class="capture-confirmation">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ t('evaluation.capture.parametersMismatch') }}</div>
        <q-space />
        <q-btn flat round dense icon="close" :aria-label="t('common.close')" @click="emit('cancel')" />
      </q-card-section>
      <q-card-section>
        <p>{{ t('evaluation.capture.parametersMismatchHelp', { dataset: mismatch.dataset_name }) }}</p>
        <div v-for="difference in mismatch.differences" :key="difference.name" class="q-mb-md">
          <strong>{{ label(difference.name) }}</strong>
          <div class="difference-values">
            <div>{{ t('evaluation.capture.sourceParameters') }}<pre>{{ pretty(difference.source_value) }}</pre></div>
            <div>{{ t('evaluation.capture.datasetParameters') }}<pre>{{ pretty(difference.dataset_value) }}</pre></div>
          </div>
        </div>
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn flat :label="t('common.cancel')" @click="emit('cancel')" />
        <q-btn color="primary" :label="t('evaluation.capture.confirmDatasetParameters')" @click="emit('confirm')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CaptureMismatch } from '../services/useCaptureConfirmation'
defineProps<{ mismatch: CaptureMismatch | null }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const { t, te } = useI18n()
const pretty = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2)
function label(name: string) { const key = `evaluation.contract.fields.${name}`; return te(key) ? t(key) : name }
</script>

<style scoped>
.capture-confirmation { width: 800px; max-width: 95vw; }
.difference-values { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow: auto; }
.q-card__actions { flex-wrap: wrap; gap: 8px; }
</style>
