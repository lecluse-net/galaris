<template>
  <q-btn
    size="sm"
    color="deep-purple"
    icon="science"
    :label="t('evaluation.capture.addToLab')"
    @click="datasetDialog = true"
  >
    <q-tooltip>{{ t(`evaluation.capture.${kind}ConversationHelp`) }}</q-tooltip>
  </q-btn>

  <LabDatasetCaptureDialog
    v-model="datasetDialog"
    :target="target"
    :source-id="sourceId"
    :source-label="sourceLabel"
  />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { LabCaptureTarget } from '../services/mechanismEvaluationService'
import LabDatasetCaptureDialog from './LabDatasetCaptureDialog.vue'

const { kind, sourceId, sourceLabel } = defineProps<{
  kind: 'text' | 'voice'
  sourceId: string
  sourceLabel: string
}>()

const { t } = useI18n()
const datasetDialog = ref(false)
const target = computed<LabCaptureTarget>(() => (
  kind === 'text' ? 'conversation_executor' : 'voice_executor'
))
</script>
