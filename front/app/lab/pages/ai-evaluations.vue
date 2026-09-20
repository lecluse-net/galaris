<template>
  <q-page class="lab-page q-pa-md">
    <PageHeader :icon="navigationIcon(currentSection.icon)"
      :title="t('evaluation.labTitle', { name: t(currentSection.titleKey) })"
      :description="t(currentSection.descriptionKey)"
    >
      <template #actions>
        <q-btn v-if="labTab === 'tasks'" color="primary" icon="refresh" :label="t('evaluation.refresh')" :loading="store.loading" @click="load" />
      </template>
    </PageHeader>

    <div class="lab-tab-content">
      <template v-if="labTab === 'tasks'">
    <q-expansion-item :label="t('evaluation.contract.diagnosisBenchmarks')" icon="science" class="q-mb-md">
      <LabWorkbench mechanism="task_analysis" :can-edit="canEdit" class="q-pa-md" />
    </q-expansion-item>
    <q-banner v-if="store.error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error_outline" /></template>
      {{ t('evaluation.loadError') }}
    </q-banner>

    <div class="lab-layout">
      <q-card flat bordered class="task-list-card">
        <q-card-section class="task-list-header">
          <div class="row items-center no-wrap q-gutter-sm">
            <q-icon name="fact_check" color="deep-purple" size="24px" />
            <div class="text-subtitle1 text-weight-medium">{{ t('evaluation.savedTasks') }}</div>
            <q-space />
            <q-badge outline color="deep-purple" :label="store.tasks.length" />
          </div>
          <div class="text-caption text-grey-7 q-mt-xs">{{ t('evaluation.savedTasksHelp') }}</div>
        </q-card-section>
        <q-separator />
        <q-card-section class="task-list-controls">
          <q-btn v-if="canEdit" outline color="deep-purple" icon="add" :label="t('evaluation.addTask')" @click="openCandidates" />
          <q-input v-model="taskFilter" dense outlined clearable :placeholder="t('evaluation.searchTasks')">
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </q-card-section>
        <q-separator />

        <q-scroll-area v-if="filteredTasks.length" class="task-list-scroll">
          <q-list separator>
            <q-item
              v-for="reference in filteredTasks"
              :key="reference.task_id"
              clickable
              :active="reference.task_id === store.selectedTaskId"
              active-class="selected-task"
              @click="selectTask(reference.task_id)"
            >
              <q-item-section avatar>
                <q-avatar :color="statusColor(reference.task?.status)" text-color="white" size="36px">
                  <q-icon :name="statusIcon(reference.task?.status)" />
                </q-avatar>
              </q-item-section>
              <q-item-section>
                <q-item-label lines="2">{{ reference.task?.label ?? t('evaluation.unavailableTask') }}</q-item-label>
                <q-item-label caption>
                  {{ reference.task?.agent_name ?? t('evaluation.noAgent') }}
                  <template v-if="reference.task"> · {{ reference.task.status }}</template>
                </q-item-label>
                <q-item-label caption class="task-uuid">{{ taskResourceUri(reference.task_id) }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn
                  v-if="canEdit"
                  flat
                  round
                  dense
                  icon="delete_outline"
                  color="negative"
                  :aria-label="t('evaluation.removeTask')"
                  :loading="removingTaskId === reference.task_id"
                  @click.stop="confirmRemove(reference.task_id)"
                >
                  <q-tooltip>{{ t('evaluation.removeTask') }}</q-tooltip>
                </q-btn>
              </q-item-section>
            </q-item>
          </q-list>
        </q-scroll-area>

        <q-card-section v-else class="empty-list text-center text-grey-7">
          <q-icon name="science" size="48px" color="grey-5" />
          <div class="q-mt-sm">{{ taskFilter ? t('evaluation.noMatchingTasks') : t('evaluation.noTasks') }}</div>
        </q-card-section>
      </q-card>

      <div class="analysis-workspace">
        <q-card v-if="selectedTask" flat bordered>
          <q-card-section>
            <div class="row items-start q-col-gutter-md">
              <div class="col">
                <div class="row items-center q-gutter-sm q-mb-xs">
                  <q-icon name="task_alt" color="deep-purple" size="md" />
                  <div class="text-h6">{{ selectedTask.label }}</div>
                  <q-badge :color="statusColor(selectedTask.status)" :label="selectedTask.status" />
                  <q-badge v-if="selectedTask.paused" color="orange" :label="t('evaluation.paused')" />
                </div>
                <div class="text-caption text-grey-7">{{ taskResourceUri(selectedTask.task_id) }}</div>
              </div>
              <div class="row q-gutter-xs">
                <q-chip dense icon="person">{{ selectedTask.agent_name ?? t('evaluation.noAgent') }}</q-chip>
                <q-chip dense icon="speed">{{ t('evaluation.effortValue', { value: selectedTask.effort }) }}</q-chip>
                <q-chip dense icon="payments">${{ selectedTask.cost.toFixed(4) }}</q-chip>
                <q-chip dense icon="history">{{ t('evaluation.attemptCount', { count: selectedTask.attempt_count }) }}</q-chip>
              </div>
            </div>
          </q-card-section>

          <q-separator />
          <q-card-section class="task-context-grid">
            <section>
              <div class="context-label">{{ t('evaluation.objective') }}</div>
              <EditorialContent :content="selectedTask.objective || t('evaluation.notProvided')" media-type="text/html" />
            </section>
            <section v-if="selectedTask.feedback">
              <div class="context-label">{{ t('evaluation.feedback') }}</div>
              <div class="pre-wrap">{{ selectedTask.feedback }}</div>
            </section>
            <section v-if="selectedTask.last_error">
              <div class="context-label text-negative">{{ t('evaluation.lastError') }}</div>
              <div class="pre-wrap text-negative">{{ selectedTask.last_error }}</div>
            </section>
          </q-card-section>

          <q-card-section class="q-pt-none">
            <q-input
              v-model="userContext"
              type="textarea"
              autogrow
              outlined
              maxlength="6000"
              counter
              :label="t('evaluation.userContext')"
              :hint="t('evaluation.userContextHelp')"
            />
            <div class="row items-center justify-between q-mt-md q-gutter-sm">
              <div class="text-caption text-grey-7">
                <q-icon name="verified_user" class="q-mr-xs" />
                {{ t('evaluation.liveEvidenceHelp') }}
              </div>
              <q-btn
                v-if="canEdit"
                color="deep-purple"
                icon="manage_search"
                :label="store.selectedDiagnoses.length ? t('evaluation.analyzeAgain') : t('evaluation.analyzeTask')"
                :loading="store.analyzingTaskId === selectedTask.task_id"
                :disable="store.config?.lab_llm_id == null"
                @click="analyzeSelected"
              >
                <q-tooltip v-if="store.config?.lab_llm_id == null">{{ t('evaluation.selectLlmFirst') }}</q-tooltip>
              </q-btn>
            </div>
          </q-card-section>
        </q-card>

        <q-card v-else-if="selectedReference" flat bordered>
          <q-card-section class="empty-workspace text-center text-negative">
            <q-icon name="link_off" size="56px" />
            <div class="text-h6 q-mt-sm">{{ t('evaluation.unavailableTask') }}</div>
            <div>{{ t('evaluation.unavailableTaskHelp') }}</div>
          </q-card-section>
        </q-card>

        <q-card v-else flat bordered>
          <q-card-section class="empty-workspace text-center text-grey-7">
            <q-icon name="manage_search" size="64px" color="grey-5" />
            <div class="text-h6 q-mt-sm">{{ t('evaluation.selectTask') }}</div>
            <div>{{ t('evaluation.selectTaskHelp') }}</div>
          </q-card-section>
        </q-card>

        <q-card v-if="selectedReference" flat bordered class="diagnosis-history-card">
          <q-card-section class="row items-center q-col-gutter-md">
            <div class="col-12 col-md">
              <div class="row items-center q-gutter-sm">
                <q-icon name="history" color="deep-purple" size="md" />
                <div>
                  <div class="text-weight-medium">{{ t('evaluation.diagnosisHistory') }}</div>
                  <div class="text-caption text-grey-7">{{ t('evaluation.diagnosisHistoryHelp') }}</div>
                </div>
              </div>
            </div>
            <div class="col-12 col-md-6">
              <q-select
                v-if="store.selectedDiagnoses.length"
                :model-value="store.selectedDiagnosisId"
                :options="diagnosisOptions"
                emit-value
                map-options
                outlined
                dense
                :label="t('evaluation.savedDiagnosis')"
                @update:model-value="selectDiagnosis"
              />
              <div v-else-if="store.diagnosesLoadingTaskId === store.selectedTaskId" class="row items-center q-gutter-sm text-grey-7">
                <q-spinner color="deep-purple" />
                <span>{{ t('evaluation.loadingDiagnoses') }}</span>
              </div>
              <div v-else class="text-grey-7">{{ t('evaluation.noDiagnoses') }}</div>
            </div>
          </q-card-section>
        </q-card>

        <EvaluationAnalysisPanel v-if="analysis" :analysis="analysis" />
      </div>
    </div>

    <q-dialog v-model="removeTaskDialog">
      <q-card class="confirm-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('evaluation.removeTask') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-separator />
        <q-card-section>{{ t('evaluation.removeTaskConfirm') }}</q-card-section>
        <q-card-actions align="right" class="q-px-md q-pb-md galaris-dialog-actions">
          <q-btn v-close-popup flat :label="t('common.cancel')" />
          <q-btn
            color="negative"
            icon="delete_outline"
            :label="t('common.delete')"
            :loading="removingTaskId !== null"
            @click="removeSelectedTask"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="candidateDialog">
      <q-card class="candidate-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="col">
            <div class="text-h6">{{ t('evaluation.addTask') }}</div>
            <div class="text-caption text-grey-7">{{ t('evaluation.addTaskHelp') }}</div>
          </div>
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-separator />
        <q-card-section>
          <q-input
            v-model="candidateSearch"
            debounce="300"
            outlined
            dense
            clearable
            :placeholder="t('evaluation.searchCandidates')"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </q-card-section>
        <q-separator />
        <q-scroll-area class="candidate-scroll">
          <div v-if="store.candidatesLoading" class="flex flex-center q-pa-xl">
            <q-spinner color="deep-purple" size="40px" />
          </div>
          <q-list v-else-if="store.candidates.length" separator>
            <q-item v-for="candidate in store.candidates" :key="candidate.task_id">
              <q-item-section avatar>
                <q-avatar :color="statusColor(candidate.status)" text-color="white">
                  <q-icon :name="statusIcon(candidate.status)" />
                </q-avatar>
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ candidate.label }}</q-item-label>
                <q-item-label caption lines="2">{{ richTextExcerpt(candidate.objective ?? '') || t('evaluation.notProvided') }}</q-item-label>
                <q-item-label caption>{{ candidate.agent_name ?? t('evaluation.noAgent') }} · {{ formatDate(candidate.updated_at) }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn
                  v-if="canEdit"
                  color="deep-purple"
                  icon="add"
                  :label="t('evaluation.add')"
                  :loading="addingTaskId === candidate.task_id"
                  @click="addCandidate(candidate.task_id)"
                />
              </q-item-section>
            </q-item>
          </q-list>
          <div v-else class="text-center text-grey-7 q-pa-xl">{{ t('evaluation.noCandidates') }}</div>
        </q-scroll-area>
      </q-card>
    </q-dialog>
      </template>

      <LabWorkbench v-else :key="labTab" :mechanism="labTab" :can-edit="canEdit" />
    </div>
    <div class="q-mt-md">
      <q-btn flat color="primary" icon="arrow_back" :label="t('common.back')" to="/lab" />
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { usePrivilegeStore } from '@/core/authorize'
import { PageHeader, richTextExcerpt, EditorialContent } from '@/core/util'
import { taskResourceUri } from '@/app/task/resourceUri'
import LabWorkbench from '../components/LabWorkbench.vue'
import EvaluationAnalysisPanel from '../components/EvaluationAnalysisPanel.vue'
import { labSections, type LabSectionKey } from '../presentation'
import { labSectionPrivileges } from '../access'
import { useEvaluationStore } from '../stores/evaluationStore'

const { section = 'tasks' } = defineProps<{ section?: LabSectionKey }>()
const { t, locale } = useI18n()
const $q = useQuasar()
const store = useEvaluationStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => (
  privilegeStore.hasPrivilege(labSectionPrivileges[section][1])
))
const labTab = computed<LabSectionKey>(() => section)
const taskFilter = ref('')
const removeTaskDialog = ref(false)
const taskToRemove = ref<string | null>(null)
const removingTaskId = ref<string | null>(null)
const candidateDialog = ref(false)
const candidateSearch = ref('')
const addingTaskId = ref<string | null>(null)
const userContext = ref('')

const currentSection = computed(() => labSections.find(item => item.key === labTab.value) ?? labSections[0])

const selectedReference = computed(() => store.selectedReference)
const selectedTask = computed(() => selectedReference.value?.task ?? null)
const analysis = computed(() => store.selectedAnalysis)
const diagnosisOptions = computed(() => store.selectedDiagnoses.map(diagnosis => ({
  value: diagnosis.id,
  label: `${formatDate(diagnosis.created_at)} · ${t(`evaluation.verdict.${diagnosis.verdict}`)} · ${diagnosis.model}`,
})))
const filteredTasks = computed(() => {
  const needle = taskFilter.value.trim().toLocaleLowerCase()
  if (!needle) return store.tasks
  return store.tasks.filter(reference => {
    const task = reference.task
    return [reference.task_id, task?.label, task?.objective, task?.agent_name, task?.status]
      .some(value => String(value ?? '').toLocaleLowerCase().includes(needle))
  })
})

watch(candidateSearch, search => {
  if (candidateDialog.value) void store.loadCandidates(search)
})
watch(() => store.selectedTaskId, () => {
  userContext.value = ''
})

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  try {
    await store.loadAll()
  } catch (error) {
    console.error('Failed to load the task analysis Lab:', error)
  }
}

async function openCandidates(): Promise<void> {
  if (!canEdit.value) return
  candidateDialog.value = true
  try {
    await store.loadCandidates(candidateSearch.value)
  } catch (error) {
    console.error('Failed to load Lab task candidates:', error)
    $q.notify({ color: 'negative', icon: 'error', message: t('evaluation.candidatesError') })
  }
}

async function addCandidate(taskId: string): Promise<void> {
  if (!canEdit.value) return
  addingTaskId.value = taskId
  try {
    await store.addTask(taskId)
    $q.notify({ color: 'positive', icon: 'science', message: t('evaluation.taskAdded') })
  } catch (error) {
    console.error('Failed to add task to the Lab:', error)
    $q.notify({ color: 'negative', icon: 'error', message: t('evaluation.taskAddError') })
  } finally {
    addingTaskId.value = null
  }
}

function confirmRemove(taskId: string): void {
  if (!canEdit.value) return
  taskToRemove.value = taskId
  removeTaskDialog.value = true
}

async function removeSelectedTask(): Promise<void> {
  const taskId = taskToRemove.value
  if (!taskId || removingTaskId.value !== null) return
  removingTaskId.value = taskId
  try {
    const selected = store.selectedTaskId === taskId
    await store.removeTask(taskId)
    if (selected && store.selectedTaskId) await store.loadDiagnoses(store.selectedTaskId)
    removeTaskDialog.value = false
    taskToRemove.value = null
  } catch (error) {
    console.error('Failed to remove task from the Lab:', error)
    $q.notify({ color: 'negative', icon: 'error', message: t('evaluation.removeTaskError') })
  } finally {
    removingTaskId.value = null
  }
}

async function selectTask(taskId: string): Promise<void> {
  store.selectTask(taskId)
  try {
    await store.loadDiagnoses(taskId)
  } catch (error) {
    console.error('Failed to load saved task diagnoses:', error)
    $q.notify({ color: 'negative', icon: 'error', message: t('evaluation.diagnosisHistoryError') })
  }
}

function selectDiagnosis(diagnosisId: string | null): void {
  if (diagnosisId) store.selectDiagnosis(diagnosisId)
}

async function analyzeSelected(): Promise<void> {
  if (!canEdit.value) return
  if (!selectedTask.value) return
  const normalizedLocale = locale.value.toLowerCase()
  const language = normalizedLocale.startsWith('fr') ? 'fr' : normalizedLocale.startsWith('zh') ? 'zh' : 'en'
  try {
    await store.analyzeTask(selectedTask.value.task_id, language, userContext.value)
    $q.notify({ color: 'positive', icon: 'save', message: t('evaluation.diagnosisSaved') })
  } catch (error) {
    console.error('Task analysis failed:', error)
    $q.notify({ color: 'negative', icon: 'error', message: t('evaluation.analysisError') })
  }
}

function statusColor(status?: string): string {
  if (status === 'SUCCESS') return 'positive'
  if (status === 'ERROR') return 'negative'
  if (status === 'EXEC' || status === 'PLAN') return 'primary'
  if (status === 'BRIEFING' || status === 'DISPATCH') return 'deep-purple'
  return 'blue-grey'
}

function statusIcon(status?: string): string {
  if (status === 'SUCCESS') return 'check'
  if (status === 'ERROR') return 'error_outline'
  if (status === 'PLAN') return 'account_tree'
  if (status === 'EXEC') return 'smart_toy'
  return 'pending'
}

function formatDate(value?: string | null): string {
  return value ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—'
}
</script>

<style scoped>
.lab-page { min-width: 0; max-width: 100%; }
.lab-tab-content { min-width: 0; max-width: 100%; }
.lab-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; align-items: start; }
.task-list-header { padding-bottom: 14px; }
.task-list-controls { display: grid; grid-template-columns: auto minmax(240px, 1fr); align-items: center; gap: 12px; padding-top: 14px; padding-bottom: 14px; }
.task-list-controls .q-btn { justify-self: start; }
.task-list-scroll { height: min(340px, calc(100vh - 420px)); min-height: 240px; }
.selected-task { background: color-mix(in srgb, #673ab7 12%, transparent); color: inherit; }
.task-uuid { font-family: monospace; overflow-wrap: anywhere; }
.empty-list { min-height: 260px; display: flex; flex-direction: column; justify-content: center; }
.analysis-workspace { display: grid; gap: 16px; min-width: 0; }
.diagnosis-history-card { border-left: 4px solid color-mix(in srgb, #673ab7 65%, white); }
.empty-workspace { min-height: 360px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.task-context-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.context-label { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: #616161; font-weight: 600; margin-bottom: 4px; }
body.body--dark .context-label { color: #bdbdbd; }
.pre-wrap { white-space: pre-wrap; overflow-wrap: anywhere; }
.confirm-dialog { width: min(480px, calc(100vw - 24px)); max-width: calc(100vw - 24px); }
.candidate-dialog { width: min(900px, calc(100vw - 24px)); max-width: calc(100vw - 24px); }
.confirm-dialog, .candidate-dialog { box-sizing: border-box; min-width: 0; }
.galaris-dialog-title > .col, .galaris-dialog-title > .text-h6 { min-width: 0; overflow-wrap: anywhere; }
.confirm-dialog :deep(.q-card__actions), .candidate-dialog :deep(.q-card__actions) { flex-wrap: wrap; gap: 8px; }
.candidate-scroll { height: min(620px, 72vh); }
@media (max-width: 900px) {
  .task-list-controls { grid-template-columns: 1fr; }
  .task-list-scroll { height: 300px; min-height: 0; }
}
@media (max-width: 700px) { .task-context-grid { grid-template-columns: 1fr; } }
@media (max-width: 599px) {
  .candidate-scroll :deep(.q-item) { flex-wrap: wrap; gap: 8px; }
  .candidate-scroll :deep(.q-item__section--side) { width: 100%; padding-left: 0; align-items: flex-start; }
}
</style>
