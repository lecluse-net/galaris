<template>
  <q-dialog v-model="open">
    <q-card class="dataset-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="col">
          <div class="text-h6">{{ t('evaluation.capture.chooseDatasetFor', { mechanism: targetLabel }) }}</div>
          <div class="text-caption text-blue-1">
            {{ t('evaluation.capture.chooseDatasetHelp', { source: sourceLabel }) }}
          </div>
        </div>
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>

      <q-separator />

      <q-card-section v-if="datasetsLoading" class="flex flex-center q-pa-xl">
        <q-spinner color="deep-purple" size="40px" />
      </q-card-section>

      <q-list v-else-if="datasets.length" separator>
        <q-item
          v-for="dataset in datasets"
          :key="dataset.id"
          clickable
          :disable="importingDatasetId !== null"
          @click="captureInDataset(dataset)"
        >
          <q-item-section avatar>
            <q-avatar color="deep-purple" text-color="white" icon="dataset" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ dataset.name }}</q-item-label>
            <q-item-label caption>
              {{ t('evaluation.capture.datasetCases', {
                ready: dataset.ready_case_count,
                total: dataset.case_count,
              }) }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-spinner v-if="importingDatasetId === dataset.id" color="deep-purple" />
            <q-icon v-else name="chevron_right" />
          </q-item-section>
        </q-item>
      </q-list>

      <q-card-section v-else class="text-center text-grey-7 q-py-xl">
        <q-icon name="dataset" color="grey-5" size="48px" />
        <div class="q-mt-sm">
          {{ t('evaluation.capture.noDatasetsFor', { mechanism: targetLabel }) }}
        </div>
      </q-card-section>

      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="between">
        <q-btn
          color="deep-purple"
          flat
          icon="add"
          :label="t('evaluation.capture.createDataset')"
          :disable="importingDatasetId !== null"
          @click="openCreateDatasetDialog"
        />
        <q-btn v-close-popup flat :label="t('common.close')" />
      </q-card-actions>
    </q-card>
  </q-dialog>

  <q-dialog v-model="createDatasetDialog">
    <q-card class="create-dataset-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('evaluation.capture.createDataset') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-separator />
      <q-form @submit="createDatasetAndCapture">
        <q-card-section>
          <q-input
            v-model="newDatasetName"
            autofocus
            outlined
            :label="t('evaluation.capture.datasetName')"
          />
        </q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md galaris-dialog-actions">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn
            type="submit"
            color="primary"
            icon="add"
            :label="t('common.create')"
            :loading="saving"
            :disable="!newDatasetName.trim()"
          />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
  <LabCaptureConfirmation :mismatch="captureMismatch" @confirm="confirmCapture" @cancel="cancelCapture" />
</template>

<script setup lang="ts">
import LabCaptureConfirmation from './LabCaptureConfirmation.vue'
import { useCaptureConfirmation } from '../services/useCaptureConfirmation'
import { computed, ref, watch } from 'vue'
import { labWorkbenchService } from '../services/labWorkbenchService'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import {
  dispatcherEvaluationService,
  type DispatcherDataset,
} from '../services/dispatcherEvaluationService'
import {
  mechanismEvaluationService,
  type EvaluationMechanism,
  type LabCaptureTarget,
  type MechanismDataset,
} from '../services/mechanismEvaluationService'

const { mismatch: captureMismatch, run: withCaptureConfirmation, confirm: confirmCapture, cancel: cancelCapture } = useCaptureConfirmation()
const { target, sourceId, sourceLabel } = defineProps<{
  target: LabCaptureTarget
  sourceId: string
  sourceLabel: string
}>()

const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{
  captured: [payload: { target: LabCaptureTarget, dataset: string }]
}>()

const { t } = useI18n()
const $q = useQuasar()
const datasets = ref<Array<DispatcherDataset | MechanismDataset>>([])
const datasetsLoading = ref(false)
const importingDatasetId = ref<string | null>(null)
const createDatasetDialog = ref(false)
const newDatasetName = ref('')
const saving = ref(false)

const targetTranslationKey = computed(() => ({
  dispatcher: 'dispatcher',
  task_analysis: 'taskAnalysis',
  briefing: 'briefing',
  planner: 'planner',
  task_executor: 'taskExecutor',
  conversation_executor: 'conversationExecutor',
  voice_executor: 'voiceExecutor',
})[target])
const targetLabel = computed(() => t(`evaluation.tabs.${targetTranslationKey.value}`))

watch(
  () => [open.value, target] as const,
  ([visible]) => {
    if (visible) void loadDatasets()
  },
)

async function loadDatasets(): Promise<void> {
  datasetsLoading.value = true
  datasets.value = []
  try {
    datasets.value = target === 'dispatcher'
      ? (await dispatcherEvaluationService.datasets()).data
      : (await mechanismEvaluationService.datasets(target)).data
  } catch (error) {
    open.value = false
    notifyError('load datasets', error)
  } finally {
    datasetsLoading.value = false
  }
}

async function importSource(datasetId: string, token?: string): Promise<'draft' | 'ready'> {
  if (target === 'task_analysis') {
    const item = await labWorkbenchService.captureTask(target, datasetId, sourceId, token)
    return item.readiness as 'draft' | 'ready'
  }
  if (target === 'dispatcher') {
    return (await dispatcherEvaluationService.importTask(datasetId, sourceId, token)).data.readiness
  } else if (target === 'briefing' || target === 'planner') {
    return (await mechanismEvaluationService.importTask(target, datasetId, sourceId, token)).data.readiness
  }
  return (await mechanismEvaluationService.importExecution(target, datasetId, sourceId, token)).data.readiness
}

async function captureInDataset(dataset: DispatcherDataset | MechanismDataset): Promise<void> {
  if (importingDatasetId.value !== null || saving.value) return
  importingDatasetId.value = dataset.id
  try {
    const readiness = await withCaptureConfirmation(token => importSource(dataset.id, token))
    if (!readiness) return
    open.value = false
    notifySuccess(dataset.name, readiness)
  } catch (error) {
    notifyError('import case', error)
  } finally {
    importingDatasetId.value = null
  }
}

function openCreateDatasetDialog(): void {
  open.value = false
  newDatasetName.value = ''
  createDatasetDialog.value = true
}

async function createDatasetAndCapture(): Promise<void> {
  const name = newDatasetName.value.trim()
  if (!name || saving.value) return
  saving.value = true
  try {
    const dataset = target === 'dispatcher'
      ? (await dispatcherEvaluationService.createDataset(name)).data
      : (await mechanismEvaluationService.createDataset(target as EvaluationMechanism, name)).data
    createDatasetDialog.value = false
    open.value = true
    const readiness = await withCaptureConfirmation(token => importSource(dataset.id, token))
    if (!readiness) return
    open.value = false
    notifySuccess(dataset.name, readiness)
  } catch (error) {
    notifyError('create dataset and import case', error)
  } finally {
    saving.value = false
  }
}

function notifySuccess(dataset: string, readiness: 'draft' | 'ready'): void {
  emit('captured', { target, dataset })
  $q.notify({
    message: t(
      readiness === 'draft'
        ? 'evaluation.capture.mechanismDraftSuccess'
        : 'evaluation.capture.mechanismSuccess',
      { mechanism: targetLabel.value, dataset },
    ),
    color: readiness === 'draft' ? 'warning' : 'positive',
    icon: readiness === 'draft' ? 'edit_note' : 'science',
    timeout: 3500,
    position: 'top',
  })
}

function notifyError(action: string, error: unknown): void {
  console.error(`AI Lab dataset capture failed (${action}):`, error)
  $q.notify({
    message: t('evaluation.capture.error'),
    color: 'negative',
    icon: 'error',
    timeout: 5000,
    position: 'top',
  })
}
</script>

<style scoped>
.dataset-dialog {
  width: min(620px, calc(100vw - 24px));
  max-width: calc(100vw - 24px);
}

.create-dataset-dialog {
  width: min(480px, calc(100vw - 24px));
  max-width: calc(100vw - 24px);
}
.dataset-dialog, .create-dataset-dialog { box-sizing: border-box; min-width: 0; }
.galaris-dialog-title > .col, .galaris-dialog-title > .text-h6 { min-width: 0; overflow-wrap: anywhere; }
.dataset-dialog :deep(.q-card__actions), .create-dataset-dialog :deep(.q-card__actions) { flex-wrap: wrap; gap: 8px; }
</style>
