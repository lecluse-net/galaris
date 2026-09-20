<template>
  <div class="lab-workbench">
    <q-card v-if="descriptor" flat bordered>
      <q-card-section class="contract-summary">
        <div><div class="text-caption">{{ t('evaluation.contract.variable') }}</div><strong>{{ variableLabel }}</strong></div>
        <div><div class="text-caption">{{ t('evaluation.contract.result') }}</div><strong>{{ resultLabel }}</strong></div>
        <div class="text-caption">{{ t('evaluation.contract.singleVariableHelp') }}</div>
      </q-card-section>
    </q-card>
    <div class="row items-center q-gutter-sm">
      <q-select v-model="datasetId" :options="datasets" option-value="id" option-label="name" emit-value map-options outlined class="col" :label="t('evaluation.contract.dataset')" :loading="loading" :disable="busy" />
      <q-btn v-if="canEdit" icon="add" color="primary" :label="t('evaluation.contract.newDataset')" :disable="loading || busy" @click="openName('dataset')" />
      <q-btn flat icon="refresh" :aria-label="t('evaluation.refresh')" @click="reload" />
      <q-chip v-if="dataset">{{ t('evaluation.insights.purposes.' + (dataset.purpose ?? 'work')) }}</q-chip>
    </div>
    <q-banner v-if="!loading && !datasets.length">{{ t('evaluation.contract.emptyDatasets') }}</q-banner>
    <q-banner v-if="datasetDirty" class="bg-orange-1 text-orange-10">{{ t('evaluation.contract.unsaved') }}</q-banner>
    <q-card v-if="dataset && descriptor" flat bordered>
      <q-tabs v-model="tab" align="left" active-color="primary">
        <q-tab name="dataset" :label="t('evaluation.contract.datasetSettings')" />
        <q-tab name="items" :label="t('evaluation.contract.items')" />
        <q-tab name="runs" :label="t('evaluation.contract.benchmarks')" />
      </q-tabs>
      <q-separator />
      <q-tab-panels v-model="tab" animated>
        <q-tab-panel name="dataset" class="dataset-settings">
          <div class="dataset-settings-content">
            <section class="dataset-section">
              <h3 class="dataset-section-title">{{ t('evaluation.contract.datasetIdentity') }}</h3>
              <div class="dataset-identity">
                <q-input v-model="dataset.name" outlined dense :label="t('evaluation.contract.name')" :readonly="!canEdit" />
                <q-select v-model="dataset.purpose" :options="purposeOptions" emit-value map-options outlined :label="t('evaluation.insights.purpose')" :readonly="!canEdit" />
                <q-input v-model="dataset.description" outlined dense type="textarea" :rows="2" :label="t('evaluation.contract.description')" :readonly="!canEdit" />
              </div>
              <p class="q-mt-md">{{ t('evaluation.insights.purposeHelp') }}</p>
            </section>
            <section class="dataset-section">
              <h3 class="dataset-section-title">{{ t('evaluation.contract.sharedParameters') }}</h3>
              <p class="dataset-section-help">{{ t('evaluation.contract.sharedParametersHelp') }}</p>
              <LabParameterEditor :key="`${dataset.id}-parameters`" v-model="dataset.parameters" :schema="descriptor.contract.parameters_schema" :defaults="descriptor.contract.parameter_defaults" :readonly="!canEdit" @invalid="datasetInvalid = $event" />
            </section>
            <section class="dataset-section">
              <h3 class="dataset-section-title">{{ t('evaluation.contract.algorithmSettings') }}</h3>
              <p class="dataset-section-help">{{ t('evaluation.contract.algorithmSettingsHelp') }}</p>
              <LabParameterEditor :key="`${dataset.id}-configuration`" v-model="dataset.configuration" :schema="descriptor.configuration_schema" :readonly="!canEdit" @invalid="configurationInvalid = $event" />
              <q-input v-if="descriptor.executor" v-model="dataset.prompt_suffix" outlined type="textarea" :rows="5" :label="t('evaluation.contract.instructionsSuffix')" :readonly="!canEdit" class="q-mt-md" />
              <q-expansion-item :label="t('evaluation.contract.algorithmContract')" icon="info_outline" class="q-mt-md">
                <JsonEditor :model-value="pretty(descriptor.algorithm)" language="json" readonly :visible-lines="12" />
              </q-expansion-item>
            </section>
          </div>
        </q-tab-panel>
        <q-tab-panel name="items">
          <div v-if="canEdit" class="row q-gutter-sm q-mb-md">
            <q-btn icon="add" color="primary" :label="t('evaluation.contract.newItem')" @click="openName('item')" />
            <q-btn icon="input" outline :label="t('evaluation.contract.capture')" @click="captureDialog = true" />
            <q-btn v-if="mechanism === 'topic_classification'" icon="forum" outline :label="t('evaluation.topicImport.title')" @click="topicImport = true" />
          </div>
          <q-select v-model="categoryFilter" clearable :options="categoryOptions" emit-value map-options outlined :label="t('evaluation.insights.categoryFilter')" class="q-mb-md" />
          <div class="row q-gutter-sm q-mb-md"><q-chip v-for="entry in coverage" :key="entry.category">{{ t('evaluation.insights.categories.' + entry.category) }} · {{ entry.count }}</q-chip></div>
          <p>{{ t('evaluation.insights.coverageHelp') }}</p>
          <q-table :rows="filteredCases" :columns="caseColumns" row-key="id" :pagination="{ rowsPerPage: 50 }" :rows-per-page-options="[10, 20, 50, 100, 500]" :grid="$q.screen.lt.md" flat>
            <template #body-cell-variable="scope"><q-td :props="scope"><span class="value-preview">{{ previewText(scope.row.input_data.variable_value) }}</span></q-td></template>
            <template #body-cell-readiness="scope"><q-td :props="scope">{{ t('evaluation.contract.status.' + scope.row.readiness) }}</q-td></template>
            <template #body-cell-actions="scope"><q-td :props="scope">
              <q-btn flat icon="edit_note" :aria-label="t('evaluation.view')" @click="openCase(scope.row)" />
              <q-btn v-if="canEdit" flat icon="delete_outline" color="negative" :aria-label="t('evaluation.contract.delete')" @click="confirmDelete('item', scope.row.id)" />
            </q-td></template>
            <template #item="scope"><div class="col-12 q-mb-sm"><q-card flat bordered @click="openCase(scope.row)"><q-card-section>
              <strong>{{ scope.row.name }}</strong><p class="value-preview">{{ previewText(scope.row.input_data.variable_value) }}</p>
              <q-btn flat icon="edit_note" :label="t('evaluation.view')" @click.stop="openCase(scope.row)" />
              <q-btn v-if="canEdit" flat icon="delete_outline" color="negative" :aria-label="t('evaluation.contract.delete')" @click.stop="confirmDelete('item', scope.row.id)" />
            </q-card-section></q-card></div></template>
          </q-table>
        </q-tab-panel>
        <q-tab-panel name="runs">
          <div class="row q-col-gutter-md q-mb-md">
            <q-input v-model.number="repetitions" type="number" min="1" max="20" outlined class="col-12 col-md-4" :label="t('evaluation.insights.repetitions')" />
            <q-input v-model.number="maxCost" type="number" min="0.0001" step="0.01" clearable outlined class="col-12 col-md-4" :label="t('evaluation.insights.budget')" />
          </div>
          <p>{{ t('evaluation.insights.budgetHelp') }}</p>
          <p>{{ t('evaluation.insights.planned', { count: cases.filter(row => row.readiness === 'ready' && row.enabled).length * repetitions }) }}</p>
          <div class="row q-col-gutter-md q-mb-md">
            <q-select v-model="candidateId" :options="config?.llms ?? []" option-value="id" option-label="label" emit-value map-options outlined class="col-12 col-md-5" :label="t('evaluation.contract.candidate')" />
            <q-select v-model="judgeId" :options="config?.llms ?? []" option-value="id" option-label="label" emit-value map-options outlined class="col-12 col-md-5" :label="t('evaluation.contract.judge')" />
            <div class="col-12 col-md-2"><q-btn v-if="canEdit" icon="play_arrow" color="primary" :label="t('evaluation.contract.start')" :loading="busy" :disable="!runSettingsValid || datasetDirty || candidateId == null || judgeId == null || !cases.some(row => row.readiness === 'ready')" @click="startRun" /></div>
          </div>
          <q-table :rows="runs" :columns="runColumns" row-key="id" :pagination="{ rowsPerPage: 50 }" :rows-per-page-options="[10, 20, 50, 100, 500]" :grid="$q.screen.lt.md" flat>
            <template #body-cell-status="scope"><q-td :props="scope">{{ t('evaluation.contract.status.' + scope.row.status) }}</q-td></template>
            <template #body-cell-progress="scope"><q-td :props="scope">
              {{ t('evaluation.contract.execution') }} {{ scope.row.completed_cases }}/{{ scope.row.total_cases }}<br />
              {{ t('evaluation.contract.judgment') }} {{ scope.row.judged_cases }}/{{ scope.row.total_cases }}
            </q-td></template>
            <template #body-cell-score="scope"><q-td :props="scope">{{ score(scope.row.score_percent) }}</q-td></template>
            <template #body-cell-actions="scope"><q-td :props="scope"><q-btn flat icon="visibility" :aria-label="t('evaluation.view')" @click="openRun(scope.row.id)" /><q-btn v-if="!active(scope.row) && scope.row.completed_cases" flat icon="rate_review" :aria-label="t('evaluation.insights.review')" @click="openReview(scope.row.id)" /></q-td></template>
            <template #item="scope"><div class="col-12 q-mb-sm"><q-card flat bordered><q-card-section>
              <div>{{ t('evaluation.contract.status.' + scope.row.status) }} · {{ score(scope.row.score_percent) }}</div>
              <div>{{ t('evaluation.contract.execution') }} {{ scope.row.completed_cases }}/{{ scope.row.total_cases }}</div>
              <div>{{ t('evaluation.contract.judgment') }} {{ scope.row.judged_cases }}/{{ scope.row.total_cases }}</div>
              <q-btn flat icon="visibility" :label="t('evaluation.view')" @click="openRun(scope.row.id)" /><q-btn v-if="!active(scope.row) && scope.row.completed_cases" flat icon="rate_review" :label="t('evaluation.insights.review')" @click="openReview(scope.row.id)" />
            </q-card-section></q-card></div></template>
          </q-table>
        </q-tab-panel>
      </q-tab-panels>
      <div v-if="canEdit && tab === 'dataset'" class="dataset-actions">
        <q-btn color="primary" icon="save" :label="t('evaluation.contract.save')" :loading="busy" :disable="datasetInvalid || configurationInvalid" @click="saveDataset" />
        <span class="text-caption" :class="datasetDirty ? 'text-warning' : 'text-grey-7'">{{ t(datasetDirty ? 'evaluation.contract.pendingChanges' : 'evaluation.contract.savedParameters') }}</span>
        <q-btn flat color="negative" icon="delete_outline" :label="$q.screen.lt.md ? undefined : t('evaluation.contract.delete')" :aria-label="t('evaluation.contract.delete')" @click="confirmDelete('dataset', dataset.id)" />
      </div>
    </q-card>

    <q-dialog v-model="caseDialog">
      <q-card v-if="editingCase && descriptor && dataset" class="wide-dialog">
        <q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ editingCase.name }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
        <q-card-section class="q-gutter-md">
          <q-input v-model="editingCase.name" outlined :label="t('evaluation.contract.name')" :readonly="!canEdit" />
          <q-select v-model="editingCase.categories" multiple use-chips :options="categoryOptions" emit-value map-options outlined :label="t('evaluation.insights.categoryLabel')" :readonly="!canEdit" />
          <LabValueEditor v-model="editingCase.input_data.variable_value" :schema="descriptor.contract.variable_schema" :label="t('evaluation.contract.testedValue', { name: variableLabel })" :readonly="!canEdit" @invalid="variableInvalid = $event" />
          <section v-if="Object.keys(descriptor.contract.context_schema?.properties ?? {}).length" class="item-context">
            <h3 class="dataset-section-title">{{ t('evaluation.contract.itemContext') }}</h3>
            <p class="dataset-section-help">{{ t('evaluation.contract.itemContextHelp') }}</p>
            <LabParameterEditor
              :key="editingCase.id" :model-value="editingCase.input_data.context ?? {}"
              :schema="descriptor.contract.context_schema" :defaults="descriptor.contract.context_defaults"
              :readonly="!canEdit" @update:model-value="editingCase.input_data.context = $event"
              @invalid="contextInvalid = $event"
            />
          </section>
          <q-separator />
          <LabValueEditor v-model="editingCase.expected_output" :schema="{ type: 'object' }" :label="t('evaluation.contract.expected', { name: resultLabel })" :readonly="!canEdit" @invalid="expectedInvalid = $event" />
          <q-expansion-item v-if="Object.keys(editingCase.source_capture).length" :label="t('evaluation.contract.provenance')">
            <JsonEditor :model-value="pretty(editingCase.source_capture)" language="json" readonly :visible-lines="12" />
          </q-expansion-item>
          <q-banner class="bg-blue-1 text-primary">{{ t('evaluation.contract.referenceHelp') }}</q-banner>
          <q-btn outline icon="preview" :label="t('evaluation.contract.preview')" :loading="busy" :disable="variableInvalid || contextInvalid" @click="previewCase" />
          <q-btn v-if="canEdit" flat icon="auto_awesome" :label="t('evaluation.contract.proposeReference')" :loading="busy" :disable="variableInvalid || contextInvalid" @click="proposeReference" />
          <q-expansion-item v-if="preview" default-opened :label="t('evaluation.contract.effectiveInput')">
            <JsonEditor :model-value="pretty(preview)" language="json" readonly :visible-lines="12" />
          </q-expansion-item>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right"><q-btn v-close-popup flat :label="t('common.cancel')" /><q-btn v-if="canEdit" color="primary" :label="t('evaluation.contract.save')" :loading="busy" :disable="variableInvalid || contextInvalid || expectedInvalid" @click="saveCase" /></q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="runDialog">
      <q-card v-if="selectedRun" class="wide-dialog">
        <q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ t('evaluation.contract.benchmarkResult') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
        <q-card-section>
          <div class="text-subtitle1">{{ t('evaluation.contract.status.' + selectedRun.status) }} · {{ score(selectedRun.score_percent) }}</div>
          <div>{{ t('evaluation.contract.candidate') }}: {{ selectedRun.llm_snapshot.label }}</div>
          <div>{{ t('evaluation.contract.judge') }}: {{ selectedRun.judge_llm_snapshot.label }}</div>
          <div>{{ t('evaluation.contract.coverage', runCoverage) }}</div>
          <div class="q-mt-md">{{ t('evaluation.contract.execution') }} {{ selectedRun.completed_cases }}/{{ selectedRun.total_cases }}</div>
          <q-linear-progress :value="selectedRun.completed_cases / Math.max(1, selectedRun.total_cases)" color="primary" />
          <div class="q-mt-md">{{ t('evaluation.contract.judgment') }} {{ selectedRun.judged_cases }}/{{ selectedRun.total_cases }}</div>
          <q-linear-progress :value="selectedRun.judged_cases / Math.max(1, selectedRun.total_cases)" color="deep-purple" />
          <div class="q-my-md">{{ t('evaluation.contract.costs', { candidate: selectedRun.candidate_cost.toFixed(4), judge: selectedRun.judge_cost.toFixed(4) }) }}</div>
          <q-banner v-if="selectedRun.status === 'partial'" class="bg-orange-1 text-orange-10">{{ t('evaluation.contract.incomplete') }}</q-banner>
          <div v-if="canEdit" class="row q-gutter-sm q-my-md">
            <q-btn v-if="active(selectedRun)" outline color="negative" icon="stop" :label="t('evaluation.contract.cancelRun')" :loading="busy" @click="cancelRun" />
            <q-btn v-if="selectedRun.status === 'cancelled'" outline icon="play_arrow" :label="t('evaluation.contract.resume')" :loading="busy" @click="resumeRun" />
            <q-btn v-if="!active(selectedRun)" outline color="deep-purple" icon="rate_review" :label="t('evaluation.contract.rejudge')" :disable="judgeId == null || !selectedRun.results.length" :loading="busy" @click="rejudgeRun" />
          </div>
          <q-btn v-if="canEdit && !active(selectedRun)" flat icon="analytics" :label="t('evaluation.dispatcher.analyzeBenchmark')" :loading="busy" @click="analyzeRun" />
          <Markdown v-if="selectedRun.analysis_markdown" :content="selectedRun.analysis_markdown" class="q-my-md" />
          <LabResultsPanel :run="selectedRun" />
          <q-separator class="q-my-md" />
          <div class="text-subtitle1">{{ t('evaluation.contract.campaigns') }}</div>
          <q-expansion-item v-for="campaign in selectedRun.campaigns" :key="campaign.id" :label="campaign.created_at" :caption="t('evaluation.contract.status.' + campaign.status)">
            <q-btn flat icon="rate_review" :label="t('evaluation.insights.review')" @click="openReview(selectedRun.id, campaign.id)" />
            <JsonEditor :model-value="pretty(campaign)" language="json" readonly :visible-lines="12" />
          </q-expansion-item>
        </q-card-section>
      </q-card>
    </q-dialog>

    <q-dialog v-model="nameDialog"><q-card class="small-dialog">
        <q-card-section class="galaris-dialog-title row items-center"><div>{{ t(nameKind === 'dataset' ? 'evaluation.contract.newDataset' : 'evaluation.contract.newItem') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
      <q-card-section><q-input v-model="newName" outlined autofocus :label="t('evaluation.contract.name')" /></q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right"><q-btn v-close-popup flat :label="t('common.cancel')" /><q-btn color="primary" :label="t('evaluation.contract.create')" :loading="busy" :disable="!newName.trim()" @click="createNamed" /></q-card-actions>
    </q-card></q-dialog>
    <q-dialog v-model="deleteDialog"><q-card class="small-dialog">
        <q-card-section class="galaris-dialog-title row items-center"><div>{{ t('evaluation.contract.delete') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
      <q-card-section>{{ t('evaluation.contract.deleteConfirm') }}</q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right"><q-btn v-close-popup flat :label="t('common.cancel')" /><q-btn color="negative" :label="t('evaluation.contract.delete')" :loading="busy" @click="deleteConfirmed" /></q-card-actions>
    </q-card></q-dialog>
    <q-dialog v-model="captureDialog"><q-card class="small-dialog">
        <q-card-section class="galaris-dialog-title row items-center"><div>{{ t('evaluation.contract.capture') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
      <q-card-section class="q-gutter-md">
        <q-input v-model="taskUri" outlined :label="t('evaluation.contract.taskUri')" />
        <q-btn outline :label="t('evaluation.contract.captureTask')" :loading="busy" :disable="!taskUri.trim()" @click="captureTask" />
        <template v-if="descriptor?.source_import && mechanism !== 'task_analysis'">
          <q-input v-model="sourceSearch" outlined :label="t('evaluation.contract.searchSource')" />
          <q-btn outline icon="search" :label="t('evaluation.contract.search')" :loading="busy" @click="searchSources" />
          <q-select v-model="sourceId" :options="sourceOptions" emit-value map-options outlined :label="t('evaluation.contract.source')" />
          <q-btn color="primary" :label="t('evaluation.contract.capture')" :loading="busy" :disable="!sourceId" @click="captureSource" />
        </template>
      </q-card-section>
    </q-card></q-dialog>
    <TopicMessageRangeImportDialog v-if="datasetId && mechanism === 'topic_classification'" v-model="topicImport" :dataset-id="datasetId" @imported="refreshDataset" />
  </div>
  <LabHumanReviewDialog v-if="reviewId" v-model="reviewOpen" :mechanism="mechanism" :run-id="reviewId" :campaign-id="reviewCampaignId" :can-edit="canEdit" />
  <LabCaptureConfirmation :mismatch="captureMismatch" @confirm="confirmCapture" @cancel="cancelCapture" />
</template>

<script setup lang="ts">
import LabResultsPanel from './LabResultsPanel.vue'
import LabHumanReviewDialog from './LabHumanReviewDialog.vue'
import { categories } from '../services/labWorkbenchService'
import LabCaptureConfirmation from './LabCaptureConfirmation.vue'
import { useCaptureConfirmation } from '../services/useCaptureConfirmation'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useQuasar, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { JsonEditor, Markdown, startVisiblePolling } from '@/core/util'
import LabValueEditor from './LabValueEditor.vue'
import LabParameterEditor from './LabParameterEditor.vue'
import TopicMessageRangeImportDialog from './TopicMessageRangeImportDialog.vue'
import { labWorkbenchService as api, type LabKey, type LabDescriptor, type LabDataset, type LabCase, type LabRun, type LabPreview } from '../services/labWorkbenchService'
import type { LabConfig } from '../services/evaluationService'

const { mechanism, canEdit } = defineProps<{ mechanism: LabKey; canEdit: boolean }>()
const { mismatch: captureMismatch, run: withCaptureConfirmation, confirm: confirmCapture, cancel: cancelCapture } = useCaptureConfirmation()
const { t, locale } = useI18n()
const $q = useQuasar()
const descriptors = ref<LabDescriptor[]>([])
const descriptor = computed(() => descriptors.value.find(item => item.key === mechanism))
const variableLabel = computed(() => t('evaluation.contract.variables.' + (descriptor.value?.contract.variable_name ?? 'request')))
const resultLabel = computed(() => t('evaluation.contract.results.' + (descriptor.value?.contract.result_name ?? 'dispatch_decision')))
const config = ref<LabConfig | null>(null)
const datasets = ref<LabDataset[]>([])
const datasetId = ref<string | null>(null)
const dataset = ref<LabDataset | null>(null)
const savedDataset = computed(() => datasets.value.find(item => item.id === datasetId.value))
const datasetDirty = computed(() => dataset.value && savedDataset.value && JSON.stringify(dataset.value) !== JSON.stringify(savedDataset.value))
const cases = ref<LabCase[]>([])
const runs = ref<LabRun[]>([])
const repetitions = ref(1), maxCost = ref<number | string | null>(null)
const budgetValue = computed(() => maxCost.value == null || maxCost.value === '' ? null : Number(maxCost.value))
const reviewId = ref<string | null>(null), reviewOpen = ref(false), categoryFilter = ref<string | null>(null)
const reviewCampaignId = ref<string | undefined>()
const purposeOptions = computed(() => ['work', 'validation', 'holdout'].map(value => ({ value, label: t('evaluation.insights.purposes.' + value) })))
const categoryOptions = computed(() => categories.map(value => ({ value, label: t('evaluation.insights.categories.' + value) })))
const filteredCases = computed(() => categoryFilter.value ? cases.value.filter(row => row.categories?.includes(categoryFilter.value!)) : cases.value)
const coverage = computed(() => categories.map(category => ({ category, count: cases.value.filter(row => row.categories?.includes(category) && row.readiness === 'ready' && row.enabled).length })))
const runSettingsValid = computed(() => Number.isInteger(repetitions.value) && repetitions.value >= 1 && repetitions.value <= 20 && (budgetValue.value == null || (Number.isFinite(budgetValue.value) && budgetValue.value > 0)))
function openReview(id: string, campaignId?: string) { reviewId.value = id; reviewCampaignId.value = campaignId; reviewOpen.value = true }
const tab = ref('items')
let dismissError: (() => void) | undefined
const loading = ref(false)
const busy = ref(false)
const candidateId = ref<number | null>(null)
const judgeId = ref<number | null>(null)
const caseDialog = ref(false)
const editingCase = ref<LabCase | null>(null)
const preview = ref<LabPreview | null>(null)
const runDialog = ref(false)
const selectedRun = ref<LabRun | null>(null)
const runCoverage = computed(() => ({
  passed: selectedRun.value?.results.filter(item => item.verdict === 'pass').length ?? 0,
  failed: selectedRun.value?.results.filter(item => item.verdict === 'fail').length ?? 0,
  judged: selectedRun.value?.results.filter(item => item.score_percent != null).length ?? 0,
  total: selectedRun.value?.total_cases ?? 0,
}))
const nameDialog = ref(false)
const nameKind = ref<'dataset' | 'item'>('dataset')
const newName = ref('')
const deleteDialog = ref(false)
const deleteTarget = ref<{ kind: 'dataset' | 'item'; id: string } | null>(null)
const datasetInvalid = ref(false), configurationInvalid = ref(false), variableInvalid = ref(false), expectedInvalid = ref(false)
const contextInvalid = ref(false)
const captureDialog = ref(false), topicImport = ref(false)
const taskUri = ref(''), sourceSearch = ref(''), sourceId = ref('')
const sourceOptions = ref<Array<{ label: string; value: string }>>([])
let generation = 0, runRequest = 0
const pretty = (value: unknown) => JSON.stringify(value ?? null, null, 2)
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const active = (run: LabRun) => ['queued', 'running'].includes(run.status)
const score = (value: number | null) => value == null ? t('evaluation.contract.unjudged') : t('evaluation.contract.score', { value: value.toFixed(1) })
const previewText = (value: unknown) => (typeof value === 'string' ? value : pretty(value)).slice(0, 160)
const caseColumns = computed<QTableColumn[]>(() => [
  { name: 'name', field: 'name', label: t('evaluation.contract.name'), align: 'left' },
  { name: 'variable', field: 'input_data', label: variableLabel.value, align: 'left' },
  { name: 'readiness', field: 'readiness', label: t('evaluation.contract.state'), align: 'left' },
  { name: 'actions', field: 'id', label: '', align: 'right' },
])
const runColumns = computed<QTableColumn[]>(() => [
  { name: 'model', field: (row: LabRun) => row.llm_snapshot.label, label: t('evaluation.contract.candidate'), align: 'left' },
  { name: 'created', field: 'created_at', label: t('evaluation.contract.date'), align: 'left', sortable: true },
  { name: 'status', field: 'status', label: t('evaluation.contract.state'), align: 'left' },
  { name: 'progress', field: 'completed_cases', label: t('evaluation.contract.progress'), align: 'left' },
  { name: 'score', field: 'score_percent', label: t('evaluation.contract.judgment'), align: 'left' },
  { name: 'actions', field: 'id', label: '', align: 'right' },
])
function report(reason: unknown) {
  dismissError?.()
  dismissError = $q.notify({
    type: 'negative',
    position: 'bottom',
    timeout: 0,
    group: false,
    message: t('evaluation.contract.error', { message: apiErrorDetail(reason) ?? String(reason) }),
    attrs: { role: 'alert' },
    actions: [{ icon: 'close', color: 'white', 'aria-label': t('common.close') }],
  })
}
async function action(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; dismissError?.()
  const current = generation
  try { await work() } catch (reason) { if (current === generation) report(reason) } finally { busy.value = false }
}
async function reload() {
  const current = ++generation, key = mechanism
  loading.value = true; dismissError?.()
  try {
    const [all, settings, list] = await Promise.all([api.descriptors(), api.config(), api.datasets(key)])
    if (current !== generation) return
    descriptors.value = all; config.value = settings; datasets.value = list
    candidateId.value ??= settings.lab_llm_id; judgeId.value ??= settings.lab_llm_id
    const id = list.some(item => item.id === datasetId.value) ? datasetId.value : list[0]?.id ?? null
    if (id !== datasetId.value) datasetId.value = id
    else await refreshDataset()
  } catch (reason) { if (current === generation) report(reason) }
  finally { if (current === generation) loading.value = false }
}
async function refreshDataset() {
  const id = datasetId.value, key = mechanism, current = generation
  if (!id) { dataset.value = null; cases.value = []; runs.value = []; return }
  const [items, history] = await Promise.all([api.cases(key, id), api.runs(key, id)])
  if (id !== datasetId.value || key !== mechanism || current !== generation) return
  dataset.value = clone(datasets.value.find(item => item.id === id) ?? null)
  cases.value = items; runs.value = history
}
watch(() => mechanism, () => { datasetId.value = null; dataset.value = null; caseDialog.value = false; runDialog.value = false; reviewOpen.value = false; reviewId.value = null; void reload() }, { immediate: true })
watch(datasetId, () => { caseDialog.value = false; runDialog.value = false; void refreshDataset().catch(report) })
const stopPolling = startVisiblePolling(async () => {
  const id = datasetId.value, key = mechanism
  if (!id || !runs.value.some(active)) return
  const history = await api.runs(key, id)
  if (id !== datasetId.value || key !== mechanism) return
  runs.value = history
  if (runDialog.value && selectedRun.value) {
    const runId = selectedRun.value.id
    const result = await api.run(key, runId)
    if (selectedRun.value?.id === runId && runDialog.value) selectedRun.value = result
  }
}, 2000, document, report)
onBeforeUnmount(() => { generation++; stopPolling(); dismissError?.() })
function openName(kind: 'dataset' | 'item') { nameKind.value = kind; newName.value = ''; nameDialog.value = true }
async function createNamed() { await action(async () => {
  if (nameKind.value === 'dataset') {
    const value = await api.createDataset(mechanism, newName.value.trim())
    datasets.value.unshift(value); datasetId.value = value.id; tab.value = 'dataset'
  } else if (datasetId.value) { const value = await api.createCase(mechanism, datasetId.value, newName.value.trim()); cases.value.unshift(value); openCase(value) }
  nameDialog.value = false
}) }
async function saveDataset() { await action(async () => {
  if (!dataset.value) return
  const saved = await api.saveDataset(mechanism, dataset.value)
  dataset.value = saved; datasets.value = datasets.value.map(item => item.id === saved.id ? saved : item)
}) }
function openCase(value: LabCase) { editingCase.value = clone(value); preview.value = null; variableInvalid.value = false; contextInvalid.value = false; expectedInvalid.value = false; caseDialog.value = true }
async function previewCase() { await action(async () => {
  const item = editingCase.value, owner = datasetId.value
  if (!item || !owner) return
  const result = await api.preview(mechanism, owner, item.input_data)
  if (editingCase.value?.id === item.id && datasetId.value === owner && caseDialog.value) preview.value = result
}) }
async function saveCase() { await action(async () => {
  if (!editingCase.value) return
  const saved = await api.saveCase(mechanism, editingCase.value)
  cases.value = cases.value.map(item => item.id === saved.id ? saved : item)
  if (editingCase.value?.id === saved.id) caseDialog.value = false
}) }
async function proposeReference() { await action(async () => {
  const item = editingCase.value
  if (!item) return
  const result = await api.expected(mechanism, item.id, item.input_data)
  if (editingCase.value?.id === item.id && caseDialog.value) editingCase.value.expected_output = result.output
}) }
async function startRun() { await action(async () => {
  if (!datasetId.value || candidateId.value == null || judgeId.value == null) return
  const value = await api.start(mechanism, datasetId.value, candidateId.value, judgeId.value, repetitions.value, budgetValue.value)
  runs.value.unshift(value); await openRun(value.id)
}) }
async function openRun(id: string) {
  const request = ++runRequest, key = mechanism, owner = datasetId.value, current = generation
  try {
    const value = await api.run(key, id)
    if (request !== runRequest || key !== mechanism || owner !== datasetId.value || current !== generation) return
    selectedRun.value = value; runDialog.value = true
  } catch (reason) { if (request === runRequest && current === generation) report(reason) }
}
async function resumeRun() { await action(async () => { if (selectedRun.value) { const id = selectedRun.value.id; await api.resume(mechanism, id); await openRun(id); await refreshRuns() } }) }
async function analyzeRun() { await action(async () => {
  if (!selectedRun.value) return
  const id = selectedRun.value.id, key = mechanism
  const result = await api.analyze(key, id, locale.value.startsWith('fr') ? 'fr' : 'en')
  if (selectedRun.value?.id === id && key === mechanism) selectedRun.value = result
}) }

async function cancelRun() { await action(async () => {
  const id = selectedRun.value?.id
  if (!id) return
  await api.cancel(mechanism, id)
  if (selectedRun.value?.id === id && runDialog.value) await openRun(id)
  await refreshRuns()
}) }
async function rejudgeRun() { await action(async () => {
  const id = selectedRun.value?.id, judge = judgeId.value
  if (!id || judge == null) return
  await api.rejudge(mechanism, id, judge)
  if (selectedRun.value?.id === id && runDialog.value) await openRun(id)
  await refreshRuns()
}) }
async function refreshRuns() {
  const id = datasetId.value, key = mechanism
  if (!id) return
  const value = await api.runs(key, id)
  if (id === datasetId.value && key === mechanism) runs.value = value
}
function confirmDelete(kind: 'dataset' | 'item', id: string) { deleteTarget.value = { kind, id }; deleteDialog.value = true }
async function deleteConfirmed() { await action(async () => {
  const target = deleteTarget.value; if (!target) return
  if (target.kind === 'dataset') { await api.deleteDataset(mechanism, target.id); await reload() }
  else { await api.deleteCase(mechanism, target.id); await refreshDataset() }
  deleteDialog.value = false
}) }
async function captureTask() { await action(async () => {
  if (!datasetId.value) return
  const id = taskUri.value.trim().replace(/^galaris:\/\/task\//, '')
  const target = datasetId.value
  const item = await withCaptureConfirmation(token => api.captureTask(mechanism, target, id, token))
  if (!item) return
  cases.value.unshift(item); captureDialog.value = false; openCase(item)
}) }
async function searchSources() { await action(async () => {
  const list = await api.candidates(mechanism, sourceSearch.value)
  sourceOptions.value = list.map(item => ({ value: String(item.source_id ?? item.task_id ?? item.id), label: String(item.label ?? item.name ?? item.task_label ?? item.id) }))
}) }
async function captureSource() { await action(async () => {
  if (!datasetId.value) return
  const target = datasetId.value, source = sourceId.value
  const item = await withCaptureConfirmation(token => mechanism === 'dispatcher'
    ? api.captureTask(mechanism, target, source, token)
    : api.captureSource(mechanism, target, source, token))
  if (!item) return
  cases.value.unshift(item); captureDialog.value = false; openCase(item)
}) }
</script>

<style scoped>
.lab-workbench { display: grid; gap: 16px; }
.dataset-settings { overflow: visible; }
.dataset-settings-content { max-width: 1080px; margin-inline: auto; display: grid; gap: 32px; }
.dataset-section-title { margin: 0 0 12px; font-size: 1.1rem; font-weight: 600; line-height: 1.5; }
.dataset-section-help { margin: -4px 0 16px; color: var(--galaris-text-muted, #657080); font-size: 0.875rem; }
.dataset-identity { display: grid; gap: 16px; align-items: start; }
.dataset-actions { position: sticky; bottom: 0; z-index: 2; display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 16px; border-top: 1px solid rgba(127, 127, 127, 0.25); background: white; }
.dataset-actions > .text-caption { flex: 1; min-width: 0; }
.body--dark .dataset-actions { background: var(--q-dark); }
.body--dark .dataset-section-help { color: #aeb8c5; }
@media (min-width: 1024px) { .dataset-identity { grid-template-columns: 1fr 2fr; } }
.contract-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); align-items: center; gap: 16px; }
.wide-dialog { width: 1180px; max-width: 96vw; }
.small-dialog { width: 560px; max-width: 96vw; }
.result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 12px; }
.value-preview { white-space: pre-wrap; overflow-wrap: anywhere; max-width: 420px; display: block; }
</style>
