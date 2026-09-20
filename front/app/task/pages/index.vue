<template>
  <q-page class="execution-monitoring-page q-pa-md">
    <PageHeader help-key="tasks" :help-text="$t('contextHelpPages.tasks')" :icon="navigationIcon('monitor_heart')" :title="$t('nav.task')" :description="$t('nav.task_desc')">
      <template #title-after>
        <q-badge color="positive" rounded>
          <q-icon name="fiber_manual_record" size="10px" class="q-mr-xs" />
          {{ $t('task.overview.live') }}
        </q-badge>
      </template>
    </PageHeader>

    <q-tabs
      v-model="activeTab"
      class="text-primary"
      active-color="primary"
      indicator-color="primary"
      align="left"
      outside-arrows
      mobile-arrows
    >
      <q-tab name="conversations" icon="forum" :label="$t('conversation.history.tab')" />
      <q-tab name="voice" icon="phone_in_talk" :label="$t('voice.history.tab')" />
      <q-tab name="tasks" icon="task" :label="$t('task.tabs.tasks')" />
      <q-tab name="llm" icon="monitor_heart" :label="$t('task.tabs.llmActivity')" />
      <q-tab
        v-if="canReadProcesses"
        name="processes"
        icon="account_tree"
        :label="$t('nav.processes')"
      />
    </q-tabs>

    <q-separator />

    <q-tab-panels v-model="activeTab" animated class="bg-transparent">
      <q-tab-panel name="conversations" class="q-pa-none q-pt-md">
        <ConversationHistory v-if="activeTab === 'conversations'" />
      </q-tab-panel>

      <q-tab-panel name="voice" class="q-pa-none q-pt-md">
        <VoiceCallHistory v-if="activeTab === 'voice'" />
      </q-tab-panel>

      <q-tab-panel name="tasks" class="q-pa-none q-pt-md">
        <template v-if="activeTab === 'tasks'">
          <div class="row q-col-gutter-md q-mb-lg">
            <div v-for="metric in taskMetrics" :key="metric.label" class="col-6 col-md-3">
              <q-card
                flat
                bordered
                class="full-height task-metric-card"
                :class="{
                  'task-metric-card--interactive': isTaskFilterMetric(metric.key),
                  'task-metric-card--active': taskMetricFilterActive(metric.key),
                  'task-metric-card--paused': metric.key === 'paused',
                  'task-metric-card--running': metric.key === 'running',
                  'task-metric-card--errors': metric.key === 'errors',
                }"
                :role="isTaskFilterMetric(metric.key) ? 'button' : undefined"
                :tabindex="isTaskFilterMetric(metric.key) ? 0 : undefined"
                :aria-pressed="isTaskFilterMetric(metric.key) ? taskMetricFilterActive(metric.key) : undefined"
                @click="toggleTaskMetricFilter(metric.key)"
                @keydown.enter.prevent="toggleTaskMetricFilter(metric.key)"
                @keydown.space.prevent="toggleTaskMetricFilter(metric.key)"
              >
                <q-card-section class="row items-center no-wrap">
                  <q-avatar :color="metric.color" text-color="white" :icon="metric.icon" />
                  <div class="col q-ml-md" style="min-width: 0">
                    <div class="text-caption text-grey-7 ellipsis">{{ metric.label }}</div>
                    <q-skeleton
                      v-if="store.recentLoading && !store.recentTasks.length"
                      type="text"
                      width="48px"
                      height="32px"
                    />
                    <div v-else class="text-h5 text-weight-medium">{{ metric.value }}</div>
                  </div>
                </q-card-section>
                <q-tooltip v-if="isTaskFilterMetric(metric.key)">
                  {{ $t(taskMetricFilterTooltip(metric.key)) }}
                </q-tooltip>
              </q-card>
            </div>
          </div>

          <!-- Task list -->
          <ActiveTasksPanel @select="onTaskSelect" />

          <!-- Large task-detail dialog -->
          <q-dialog
            v-model="detailDialogOpen"
            transition-show="slide-up"
            transition-hide="slide-down"
          >
            <q-card class="task-detail-dialog galaris-detail-dialog">
              <q-card-section class="galaris-dialog-title row items-center justify-between">
                <div class="text-h6">{{ $t('task.detailTitle') }}</div>
                <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup />
              </q-card-section>

              <q-card-section class="task-detail-content">
                <TaskDetail
                  :task-id="selectedTaskId"
                  @refresh="refreshTaskDetail"
                  @delete="onDeleteFromDetail"
                  @task-change="onTaskChange"
                />
              </q-card-section>
            </q-card>
          </q-dialog>

          <!-- Deletion confirmation dialog. -->
          <q-dialog v-model="deleteDialogOpen">
            <q-card>
              <q-card-section class="galaris-dialog-title row items-center">
                <q-icon name="warning" size="28px" />
                <span class="q-ml-sm text-h6">{{ $t('task.deleteConfirm') }}</span>
                <q-space />
                <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
              </q-card-section>
              <q-card-section>
                <p>{{ $t('task.deleteMessage', { label: taskToDelete?.label }) }}</p>
                <p class="text-caption text-grey">{{ $t('task.deleteReversible') }}</p>
              </q-card-section>
              <q-card-actions class="galaris-dialog-actions" align="right">
                <q-btn flat :label="$t('common.cancel')" color="grey" v-close-popup />
                <q-btn v-if="canEdit" flat :label="$t('common.delete')" color="negative" @click="confirmDelete" :loading="deleteLoading" />
              </q-card-actions>
            </q-card>
          </q-dialog>

        </template>
      </q-tab-panel>

      <q-tab-panel name="llm" class="q-pa-none q-pt-md">
        <LlmActivityPanel v-if="activeTab === 'llm'" />
      </q-tab-panel>

      <q-tab-panel v-if="canReadProcesses" name="processes" class="q-pa-none q-pt-md">
        <ProcessRunsPanel v-if="activeTab === 'processes'" />
      </q-tab-panel>
    </q-tab-panels>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { apiErrorDetail } from '@/core/api'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useTaskStore } from '../stores/taskStore'
import { usePrivilegeStore } from '@/core/authorize'
import { privileges } from '@/core/authorize'
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import TaskDetail from '../components/TaskDetail.vue'
import ActiveTasksPanel from '../components/ActiveTasksPanel.vue'
import LlmActivityPanel from '@/app/llm/components/LlmActivityPanel.vue'
import ConversationHistory from '@/app/conversation/components/ConversationHistory.vue'
import VoiceCallHistory from '@/app/voice/components/VoiceCallHistory.vue'
import ProcessRunsPanel from '@/app/process/components/ProcessRunsPanel.vue'
import type { Task, TaskFull } from '../types'

type ActivityTab = 'tasks' | 'conversations' | 'voice' | 'llm' | 'processes'

const $q = useQuasar()
const { t } = useI18n()
const store = useTaskStore()
const privilegeStore = usePrivilegeStore()
const route = useRoute()
const router = useRouter()
const canReadProcesses = computed(() => (
  privilegeStore.hasPrivilege(privileges.PROCESS_READ)
  || privilegeStore.hasPrivilege(privileges.PROCESS_ADMIN)
))
const activeTab = ref<ActivityTab>(
  route.query.task_id ? 'tasks' : tabFromQuery(route.query.tab),
)

// Permissions
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TASK_EDIT))

const taskMetrics = computed(() => {
  const summary = store.recentSummary
  return [
    {
      key: 'completed',
      label: t('task.overview.metrics.completed'),
      value: summary.completed,
      icon: 'check_circle',
      color: 'positive',
    },
    {
      key: 'paused',
      label: t('task.overview.metrics.paused'),
      value: summary.paused,
      icon: 'pause_circle',
      color: 'warning',
    },
    {
      key: 'running',
      label: t('task.overview.metrics.running'),
      value: summary.running,
      icon: 'motion_photos_on',
      color: 'primary',
    },
    {
      key: 'errors',
      label: t('task.overview.metrics.errors'),
      value: summary.errors,
      icon: 'error',
      color: 'negative',
    },
  ]
})

type TaskFilterMetric = 'paused' | 'running' | 'errors'

function isTaskFilterMetric(key: string): key is TaskFilterMetric {
  return key === 'paused' || key === 'running' || key === 'errors'
}

function taskMetricFilterActive(key: string): boolean {
  if (key === 'paused') return store.recentPausedOnly
  if (key === 'running') return store.recentRunningOnly
  if (key === 'errors') return store.recentErrorsOnly
  return false
}

function taskMetricFilterTooltip(key: TaskFilterMetric): string {
  if (taskMetricFilterActive(key)) return 'task.overview.metrics.showAll'
  if (key === 'paused') return 'task.overview.metrics.showPausedOnly'
  if (key === 'running') return 'task.overview.metrics.showRunningOnly'
  return 'task.overview.metrics.showErrorsOnly'
}

function toggleTaskMetricFilter(key: string): void {
  if (key === 'paused') {
    store.setRecentPausedOnly(!store.recentPausedOnly)
  } else if (key === 'running') {
    store.setRecentRunningOnly(!store.recentRunningOnly)
  } else if (key === 'errors') {
    store.setRecentErrorsOnly(!store.recentErrorsOnly)
  }
}

// Selected task state
const selectedTaskId = ref<string | null>(null)

// Dialog states
const detailDialogOpen = ref(false)
const deleteDialogOpen = ref(false)
const deleteLoading = ref(false)

const taskToDelete = ref<Task | null>(null)

// Initialize
onMounted(() => {
  if (activeTab.value === 'tasks') {
    store.subscribeToTasks()
    openTaskFromQuery(route.query.task_id)
  }
})

onUnmounted(() => {
  store.unsubscribeFromTasks()
})

watch(activeTab, tab => {
  if (tab === 'tasks') {
    store.subscribeToTasks()
  } else {
    store.unsubscribeFromTasks()
  }

  const query = { ...route.query }
  if (tab === 'processes') {
    query.tab = 'processes'
    delete query.task_id
  } else if (tab === 'llm') {
    query.tab = 'llm'
    delete query.task_id
  } else if (tab === 'voice') {
    query.tab = 'voice'
    delete query.task_id
  } else if (tab === 'tasks') {
    query.tab = 'tasks'
  } else {
    delete query.tab
    delete query.task_id
  }
  void router.replace({ query })
})

watch(() => route.query.tab, value => {
  const tab = tabFromQuery(value)
  if (activeTab.value !== tab) activeTab.value = tab
})

watch(canReadProcesses, allowed => {
  if (allowed && route.query.tab === 'processes') {
    activeTab.value = 'processes'
  } else if (!allowed && activeTab.value === 'processes') {
    activeTab.value = 'conversations'
  }
})

watch(() => route.query.task_id, openTaskFromQuery)

function tabFromQuery(value: unknown): ActivityTab {
  if (value === 'processes' && canReadProcesses.value) return 'processes'
  if (value === 'llm') return 'llm'
  if (value === 'voice') return 'voice'
  if (value === 'tasks') return 'tasks'
  return 'conversations'
}

function openTaskFromQuery(value: unknown) {
  const taskId = Array.isArray(value) ? value[0] : value
  if (typeof taskId !== 'string' || !taskId) return
  activeTab.value = 'tasks'
  selectedTaskId.value = taskId
  detailDialogOpen.value = true
}

async function refreshTaskDetail() {
  // TaskDetail manages its own refresh lifecycle.
}

function onTaskSelect(taskId: string) {
  selectedTaskId.value = taskId
  detailDialogOpen.value = true
}

function onTaskChange(taskId: string) {
  selectedTaskId.value = taskId
}

function onDeleteFromDetail(task: TaskFull) {
  if (!canEdit.value) {
    $q.notify({ type: 'negative', message: t('task.notify.deleteDenied') })
    return
  }
  taskToDelete.value = task as unknown as Task
  detailDialogOpen.value = false
  deleteDialogOpen.value = true
}

async function confirmDelete() {
  if (!taskToDelete.value) return
  deleteLoading.value = true
  try {
    await store.deleteTask(taskToDelete.value.id)
    $q.notify({ type: 'positive', message: t('task.notify.deleted') })
    if (selectedTaskId.value === taskToDelete.value.id) {
      selectedTaskId.value = null
    }
    await store.fetchRecentTasks()
    deleteDialogOpen.value = false
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: apiErrorDetail(error) || t('task.notify.deleteError'),
    })
  } finally {
    deleteLoading.value = false
    taskToDelete.value = null
  }
}
</script>

<style scoped>
.task-detail-dialog {
  height: calc(100vh - 32px);
  display: flex;
  flex-direction: column;
}

.task-detail-content {
  flex: 1;
  overflow: auto;
  padding: 0;
}

.task-metric-card {
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.task-metric-card--interactive {
  cursor: pointer;
}

.task-metric-card--paused {
  --task-metric-accent: var(--q-warning);
  --task-metric-shadow: rgb(242 192 55 / 18%);
}

.task-metric-card--running {
  --task-metric-accent: var(--q-primary);
  --task-metric-shadow: rgb(25 118 210 / 18%);
}

.task-metric-card--errors {
  --task-metric-accent: var(--q-negative);
  --task-metric-shadow: rgb(193 40 46 / 18%);
}

.task-metric-card--interactive:hover,
.task-metric-card--interactive:focus-visible {
  border-color: var(--task-metric-accent);
  box-shadow: 0 4px 14px var(--task-metric-shadow);
  outline: none;
  transform: translateY(-1px);
}

.task-metric-card--active {
  border-color: var(--task-metric-accent);
  box-shadow: 0 0 0 1px var(--task-metric-accent), 0 5px 16px var(--task-metric-shadow);
}

@media (max-width: 599px) {
  .execution-monitoring-page {
    padding: 8px;
  }

  .task-metric-card :deep(.q-card__section) {
    padding: 12px;
  }

  .task-metric-card :deep(.q-avatar) {
    font-size: 36px;
  }

  .task-metric-card :deep(.q-ml-md) {
    margin-left: 8px;
  }
}
</style>
