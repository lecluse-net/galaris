<template>
  <section class="agent-tasks-panel" :class="{ 'agent-tasks-panel--embedded': embedded }">
    <q-toolbar v-if="!embedded" class="agent-tasks-toolbar">
      <q-btn v-if="showBack" flat round dense icon="arrow_back" :aria-label="t('chat.backToConversation')" @click="$emit('back')" />
      <q-icon name="account_tree" color="primary" size="21px" class="q-mr-sm" />
      <q-toolbar-title class="agent-tasks-title">
        <div>{{ t('chat.tasks') }}</div>
        <div v-if="canRead" class="agent-tasks-count">{{ t('chat.taskCount', { count: total }) }}</div>
      </q-toolbar-title>
      <q-badge rounded :color="connected ? 'positive' : 'grey-6'" class="agent-tasks-live">
        <q-icon name="fiber_manual_record" size="8px" class="q-mr-xs" />
        {{ t(connected ? 'chat.tasksLive' : 'chat.tasksReconnecting') }}
      </q-badge>
      <q-btn v-if="canRead" flat round dense icon="refresh" :loading="loading" :aria-label="t('chat.refreshTasks')" @click="load(true)" />
    </q-toolbar>
    <q-separator v-if="!embedded" />

    <div v-if="!canRead" class="agent-tasks-state text-grey-7">
      <q-icon name="lock" size="28px" />
      <span>{{ t('chat.tasksUnavailable') }}</span>
    </div>
    <div v-else-if="error && !tasks.length" class="agent-tasks-state text-negative">
      <q-icon name="error_outline" size="28px" />
      <span>{{ error }}</span>
      <q-btn flat dense no-caps color="primary" :label="t('chat.retryTasks')" @click="load(true)" />
    </div>
    <div v-else class="agent-tasks-scroll-zone">
      <q-scroll-area ref="taskScrollArea" class="agent-tasks-scroll" @scroll="onTaskScroll">
        <div v-if="loading && !tasks.length && !hasCompletedInitialTaskLoad" class="agent-tasks-state text-grey-7"><q-spinner color="primary" size="28px" /></div>
        <div v-else-if="!tasks.length" class="agent-tasks-state text-grey-7">
          <q-icon name="account_tree" size="32px" />
          <span>{{ t('chat.noAgentTasks') }}</span>
        </div>
        <q-list v-else class="agent-task-list">
          <div v-if="loadingOlder" class="agent-tasks-load-older"><q-spinner color="primary" size="20px" /></div>
          <q-item
            v-for="row in flatTasks"
            :key="row.task.id"
            clickable
            class="agent-task-row"
            :class="{
              'agent-task-row--collapsed': !isTaskExpanded(row.task),
              'agent-task-row--error': row.task.status === 'ERROR',
            }"
            :style="rowStyle(row.depth)"
            :aria-label="t('chat.openTask', { label: taskDisplayLabel(row.task) })"
            @click="openTask(row.task.id)"
          >
            <q-item-section class="agent-task-main">
              <div class="agent-task-header" :class="{ 'agent-task-header--collapsed': !isTaskExpanded(row.task) }">
              <div v-if="isTaskExpanded(row.task)" class="agent-task-avatar">
                <InternalAgentAvatar
                  v-if="row.task.agent_id != null"
                  :agent-id="row.task.agent_id"
                  :name="taskAgentName(row.task)"
                  size="42px"
                />
                <q-avatar v-else size="42px" color="grey-3" text-color="grey-7" icon="person_off" />
                <span
                  class="agent-task-status-dot"
                  role="img"
                  :aria-label="t(pauseBadge(row.task)?.labelKey ?? `task.status.${row.task.status}`)"
                >
                  <q-spinner v-if="shouldAnimateTaskStatus({ ...row.task, operationalState: activitySnapshots[row.task.id]?.operational.operational_state })" :color="getTaskOperationalColor(row.task)" size="14px" />
                  <q-icon v-else :name="getTaskOperationalIcon(row.task)" :color="getTaskOperationalColor(row.task)" size="15px" />
                </span>
              </div>
              <div class="agent-task-heading">
                <div class="agent-task-title-row">
                  <button
                    type="button"
                    class="agent-task-expansion-toggle"
                    :aria-expanded="isTaskExpanded(row.task)"
                    :aria-label="t(isTaskExpanded(row.task) ? 'chat.collapseTask' : 'chat.expandTask')"
                    @click.stop="toggleTask(row.task)"
                  >
                    <q-icon :name="isTaskExpanded(row.task) ? 'expand_less' : 'expand_more'" size="18px" />
                    <span class="agent-task-label">{{ taskDisplayLabel(row.task) }}</span>
                  </button>
                  <div v-if="canEdit && isTaskExpanded(row.task)" class="agent-task-actions" @click.stop>
                    <q-btn
                      v-if="canPauseTask(row.task)"
                      flat
                      round
                      dense
                      size="sm"
                      color="orange-8"
                      icon="pause"
                      class="agent-task-action"
                      :loading="taskAction(row.task.id) === 'pause'"
                      :disable="taskAction(row.task.id) !== null"
                      :aria-label="t('task.detail.pauseTooltip')"
                      @click.stop="pauseTask(row.task)"
                    >
                      <q-tooltip>{{ t('task.detail.pauseTooltip') }}</q-tooltip>
                    </q-btn>
                    <q-btn
                      v-if="canResumeTask(row.task)"
                      flat
                      round
                      dense
                      size="sm"
                      color="positive"
                      icon="play_arrow"
                      class="agent-task-action"
                      :loading="taskAction(row.task.id) === 'resume'"
                      :disable="taskAction(row.task.id) !== null"
                      :aria-label="t('task.detail.resumeTooltip')"
                      @click.stop="resumeTask(row.task)"
                    >
                      <q-tooltip>{{ t('task.detail.resumeTooltip') }}</q-tooltip>
                    </q-btn>
                    <q-btn
                      v-if="canForceTerminateTask(row.task)"
                      flat
                      round
                      dense
                      size="sm"
                      color="negative"
                      icon="cancel"
                      class="agent-task-action"
                      :loading="taskAction(row.task.id) === 'force-terminate'"
                      :disable="taskAction(row.task.id) !== null"
                      :aria-label="t('task.detail.forceTerminateTooltip')"
                      @click.stop="confirmTaskForceTerminate(row.task)"
                    >
                      <q-tooltip>{{ t('task.detail.forceTerminateTooltip') }}</q-tooltip>
                    </q-btn>
                    <q-btn
                      flat
                      round
                      dense
                      size="sm"
                      color="negative"
                      icon="delete"
                      class="agent-task-action"
                      :loading="taskAction(row.task.id) === 'delete'"
                      :disable="taskAction(row.task.id) !== null"
                      :aria-label="t('task.detail.deleteTooltip')"
                      @click.stop="confirmTaskDelete(row.task)"
                    >
                      <q-tooltip>{{ t('task.detail.deleteTooltip') }}</q-tooltip>
                    </q-btn>
                  </div>
                  <q-icon
                    v-if="isTaskExpanded(row.task) && pauseBadge(row.task)"
                    :name="pauseBadge(row.task)!.icon"
                    :color="pauseBadge(row.task)!.waiting ? 'blue-7' : 'orange-8'"
                    size="17px"
                    class="agent-task-pause-icon"
                  ><q-tooltip>{{ t(pauseBadge(row.task)!.labelKey) }}</q-tooltip></q-icon>
                  <q-btn
                    flat
                    dense
                    no-caps
                    color="primary"
                    icon="info_outline"
                    :label="t('chat.details')"
                    class="agent-task-details"
                    @click.stop="openTask(row.task.id)"
                  />
                </div>
                <TaskActivitySummary v-if="isTaskExpanded(row.task)" :activity="activitySnapshots[row.task.id]" :unavailable="activityUnavailable" />
                <CompactTaskOperations
                  v-if="isTaskExpanded(row.task)"
                  display="summary"
                  :execution-result="resultFor(row.task) ?? undefined"
                  :status="row.task.status"
                  :paused="row.task.paused"
                  :operational-state="activitySnapshots[row.task.id]?.operational.operational_state"
                  class="agent-task-previous-operations"
                />
                </div>
              </div>
              <div v-if="isTaskExpanded(row.task) && row.task.objective" class="agent-task-objective">
                <q-icon name="outlined_flag" size="14px" class="agent-task-objective-icon" />
                <span>{{ richTextExcerpt(row.task.objective) }}</span>
              </div>
              <CompactTaskOperations
                v-if="isTaskExpanded(row.task)"
                display="operations"
                :execution-result="resultFor(row.task) ?? undefined"
                :status="row.task.status"
                :paused="row.task.paused"
                :operational-state="activitySnapshots[row.task.id]?.operational.operational_state"
                class="agent-task-operations"
              />
              <div v-if="isTaskExpanded(row.task)" class="agent-task-meta">
                <time :datetime="row.task.created_at">{{ formatTimestamp(row.task) }}</time>
                <TopicBadge
                  v-if="row.task.topic_id"
                  :topic-id="row.task.topic_id"
                  :title="topicTitle(row.task.topic_id)"
                  subject-kind="task"
                  :subject-id="row.task.id"
                  class="agent-task-topic"
                />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
        <div v-if="error && tasks.length" class="agent-tasks-inline-error text-negative"><q-icon name="warning" size="14px" /> {{ error }}</div>
      </q-scroll-area>
      <transition name="scroll-to-bottom">
        <q-btn
          v-if="showScrollToBottom"
          class="scroll-to-bottom-button"
          flat
          round
          dense
          icon="keyboard_arrow_down"
          :aria-label="t('chat.scrollToBottom')"
          @click="scrollTasksToBottom"
        ><q-tooltip>{{ t('chat.scrollToBottom') }}</q-tooltip></q-btn>
      </transition>
    </div>

    <q-dialog v-model="detailDialogOpen" transition-show="slide-up" transition-hide="slide-down">
      <q-card class="task-detail-dialog galaris-detail-dialog">
        <q-card-section class="galaris-dialog-title row items-center justify-between">
          <div class="text-h6">{{ t('task.detailTitle') }}</div>
          <q-btn v-close-popup icon="close" flat round dense :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section class="task-detail-content">
          <TaskDetail
            :task-id="selectedTaskId"
            @refresh="refreshTaskDetail"
            @delete="confirmTaskDelete"
            @task-change="selectedTaskId = $event"
          />
        </q-card-section>
      </q-card>
    </q-dialog>
  </section>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { richTextExcerpt } from '@/core/util'
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { websocket } from '@/core/websocket'
import {
  getTaskOperationalColor,
  getTaskOperationalIcon,
  isUserPaused,
  pauseBadge,
  shouldAnimateTaskStatus,
  TaskDetail,
  TaskActivitySummary,
  useTaskActivity,
  useTaskStore,
  type Task,
} from '@/app/task'
import { TopicBadge, useTopicRefs } from '@/app/topic'
import { chatService } from '../services/chatService'
import type { ConversationTask } from '../types'
import CompactTaskOperations from './CompactTaskOperations.vue'
import InternalAgentAvatar from './InternalAgentAvatar.vue'

const props = withDefaults(defineProps<{ roomId: string; fromMessageId?: string | null; conversationAgentId?: number | null; viewerAgentId?: number | null; canRead?: boolean; showBack?: boolean; embedded?: boolean }>(), {
  fromMessageId: null,
  conversationAgentId: null,
  viewerAgentId: null,
  canRead: false,
  showBack: false,
  embedded: false,
})
defineEmits<{ back: [] }>()

const $q = useQuasar()
const { t, locale } = useI18n()
const taskStore = useTaskStore()
const privilegeStore = usePrivilegeStore()
const tasks = ref<ConversationTask[]>([])
const { snapshots: activitySnapshots, unavailable: activityUnavailable, resultFor } = useTaskActivity(() => tasks.value)
const agentNames = ref<Map<number, string>>(new Map())
const total = ref(0)
const loading = ref(false)
const loadingOlder = ref(false)
const hasCompletedInitialTaskLoad = ref(false)
const page = ref(1)
const error = ref('')
const selectedTaskId = ref<string | null>(null)
const detailDialogOpen = ref(false)
const pendingTaskActions = ref<Record<string, TaskAction | undefined>>({})
const taskExpansionOverrides = ref<Record<string, boolean | undefined>>({})
const showScrollToBottom = ref(false)
const connected = websocket.isConnected
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TASK_EDIT))
const { resolveTopicRefs, topicTitle } = useTopicRefs()
let requestSequence = 0
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let scrollFrame: number | null = null
let scrollVisibilityFrame: number | null = null
let taskScrollResizeObserver: ResizeObserver | null = null
let pendingBottomScroll = false
let subscribed = false
let agentNamesLoaded = false
const createdTaskIdsAwaitingRefresh = new Set<string>()
const TASK_PAGE_SIZE = 10
const TASK_BOTTOM_THRESHOLD = 24

type TaskSnapshotEvent = { data?: Task }
type TaskDeleteEvent = { data?: { id?: string } }
type FlatTask = { task: ConversationTask; depth: number }
type TaskAction = 'pause' | 'resume' | 'force-terminate' | 'delete'
type TaskScrollArea = {
  $el: HTMLElement
  setScrollPosition: (axis: 'vertical', offset: number, duration?: number) => void
  getScrollTarget: () => HTMLElement
}
type TaskScrollInfo = { verticalPosition: number; verticalSize: number; verticalContainerSize: number }

const taskScrollArea = useTemplateRef<TaskScrollArea>('taskScrollArea')
const hasOlderTasks = computed(() => tasks.value.length < total.value)

function displayedAt(task: Task): number {
  const messageSeconds = Number(task.data?.time)
  if (Number.isFinite(messageSeconds) && messageSeconds > 0) return messageSeconds * 1_000
  const timestamp = Date.parse(task.created_at ?? task.updated_at ?? '')
  return Number.isFinite(timestamp) ? timestamp : 0
}

function sortOldest(left: ConversationTask, right: ConversationTask): number {
  return displayedAt(left) - displayedAt(right) || left.id.localeCompare(right.id)
}

const flatTasks = computed<FlatTask[]>(() => {
  const byId = new Map(tasks.value.map(task => [task.id, task]))
  const children = new Map<string, ConversationTask[]>()
  const roots: ConversationTask[] = []
  for (const task of tasks.value) {
    const parentId = task.tree_parent_id
    if (!parentId || !byId.has(parentId) || parentId === task.id) {
      roots.push(task)
      continue
    }
    const siblings = children.get(parentId) ?? []
    siblings.push(task)
    children.set(parentId, siblings)
  }
  roots.sort(sortOldest)
  for (const siblings of children.values()) siblings.sort(sortOldest)

  const rows: FlatTask[] = []
  const visited = new Set<string>()
  function visit(task: ConversationTask, depth: number): void {
    if (visited.has(task.id)) return
    visited.add(task.id)
    rows.push({ task, depth })
    for (const child of children.get(task.id) ?? []) visit(child, depth + 1)
  }
  for (const root of roots) visit(root, 0)
  for (const task of [...tasks.value].sort(sortOldest)) visit(task, 0)
  return rows
})

function rowStyle(depth: number): Record<string, string> {
  return { paddingLeft: `${7 + Math.min(depth, 5) * 20}px` }
}

function isTaskInProgress(task: Task): boolean {
  return !['SUCCESS', 'ERROR'].includes(task.status)
}

function isTaskExpanded(task: Task): boolean {
  return taskExpansionOverrides.value[task.id] ?? isTaskInProgress(task)
}

function toggleTask(task: Task): void {
  taskExpansionOverrides.value[task.id] = !isTaskExpanded(task)
  updateScrollButtonVisibility()
}

function taskAgentName(task: ConversationTask): string {
  if (task.agent_id == null) return t('task.list.noAgent')
  return agentNames.value.get(task.agent_id) ?? t('task.list.agentId', { id: task.agent_id })
}

function taskDisplayLabel(task: ConversationTask): string {
  if (
    props.conversationAgentId == null
    || task.agent_id == null
    || task.agent_id === props.conversationAgentId
  ) return task.label
  return t('chat.delegatedTaskLabel', { agent: taskAgentName(task), title: task.label })
}

async function loadAgentNames(): Promise<void> {
  if (agentNamesLoaded) return
  try {
    const catalog = await chatService.recipients()
    agentNames.value = new Map(catalog.agents.map(agent => [agent.agent_id, agent.display_name]))
    agentNamesLoaded = true
  } catch {
    // The task list remains usable with the translated agent ID as a fallback.
  }
}

function formatTimestamp(task: Task): string {
  const timestamp = displayedAt(task)
  if (!timestamp) return ''
  const value = new Date(timestamp)
  const today = new Date()
  const sameDay = value.toDateString() === today.toDateString()
  return new Intl.DateTimeFormat(locale.value, sameDay
    ? { hour: '2-digit', minute: '2-digit' }
    : { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }
  ).format(value)
}

function taskAction(taskId: string): TaskAction | null {
  return pendingTaskActions.value[taskId] ?? null
}

function executionExpected(task: Task): boolean {
  if (task.execution_expected === false) return false
  return task.coordination_type !== 'await_reply'
    && task.is_coordination !== true
    && !task.data?.awaiting_reply
}

function canPauseTask(task: Task): boolean {
  return executionExpected(task)
    && !isUserPaused(task)
    && !['SUCCESS', 'ERROR'].includes(task.status)
}

function canResumeTask(task: Task): boolean {
  return executionExpected(task)
    && isUserPaused(task)
    && !['SUCCESS', 'ERROR'].includes(task.status)
}

function canForceTerminateTask(task: Task): boolean {
  return !['SUCCESS', 'ERROR'].includes(task.status)
}

function applyLocalTaskSnapshot(snapshot: Task): void {
  tasks.value = tasks.value.map(task => task.id === snapshot.id
    ? { ...task, ...snapshot, tree_parent_id: task.tree_parent_id, directly_linked: task.directly_linked }
    : task)
}

async function pauseTask(task: Task): Promise<void> {
  if (!canEdit.value || !canPauseTask(task) || taskAction(task.id)) return
  pendingTaskActions.value[task.id] = 'pause'
  try {
    const updated = await taskStore.pauseTask(task.id)
    applyLocalTaskSnapshot(updated)
    $q.notify({
      message: t('task.notify.pauseSuccess'),
      color: 'positive',
      icon: 'pause_circle',
      timeout: 3000,
      position: 'top',
    })
    scheduleRefresh()
  } catch (caught) {
    $q.notify({
      message: apiErrorDetail(caught) || t('task.notify.pauseError'),
      color: 'negative',
      icon: 'error',
      timeout: 5000,
      position: 'top',
    })
  } finally {
    delete pendingTaskActions.value[task.id]
  }
}

async function resumeTask(task: Task): Promise<void> {
  if (!canEdit.value || !canResumeTask(task) || taskAction(task.id)) return
  pendingTaskActions.value[task.id] = 'resume'
  try {
    const updated = await taskStore.resumeTask(task.id)
    applyLocalTaskSnapshot(updated)
    $q.notify({
      message: t('task.notify.resumeSuccess'),
      color: 'positive',
      icon: 'play_circle',
      timeout: 3000,
      position: 'top',
    })
    scheduleRefresh()
  } catch (caught) {
    $q.notify({
      message: apiErrorDetail(caught) || t('task.notify.resumeError'),
      color: 'negative',
      icon: 'error',
      timeout: 5000,
      position: 'top',
    })
  } finally {
    delete pendingTaskActions.value[task.id]
  }
}

function confirmTaskForceTerminate(task: Task): void {
  if (!canEdit.value || !canForceTerminateTask(task) || taskAction(task.id)) return
  showConfirmationDialog({
    title: t('task.detail.forceTerminateConfirmTitle'),
    message: t('task.detail.forceTerminateConfirmMessage', { label: task.label }),
    cancel: true,
    ok: {
      label: t('task.detail.forceTerminateConfirmAction'),
      color: 'negative',
    },
    focus: 'cancel',
  }).onOk(() => {
    void forceTerminateTask(task)
  })
}

async function forceTerminateTask(task: Task): Promise<void> {
  if (!canEdit.value || !canForceTerminateTask(task) || taskAction(task.id)) return
  pendingTaskActions.value[task.id] = 'force-terminate'
  try {
    const updated = await taskStore.forceTerminateTask(task.id, task.revision)
    applyLocalTaskSnapshot(updated)
    $q.notify({
      message: t('task.notify.forceTerminateSuccess'),
      color: 'positive',
      icon: 'check_circle',
      timeout: 4000,
      position: 'top',
    })
    scheduleRefresh()
  } catch (caught) {
    $q.notify({
      message: apiErrorDetail(caught) || t('task.notify.forceTerminateError'),
      color: 'negative',
      icon: 'error',
      timeout: 5000,
      position: 'top',
    })
  } finally {
    delete pendingTaskActions.value[task.id]
  }
}

async function load(reset = true, scrollAfterLoad = false): Promise<void> {
  const sequence = ++requestSequence
  // This request supersedes any older-page request, including on live refresh.
  loadingOlder.value = false
  if (!props.canRead || !props.fromMessageId) {
    tasks.value = []
    total.value = 0
    page.value = 1
    error.value = ''
    hasCompletedInitialTaskLoad.value = true
    return
  }
  loading.value = true
  try {
    const knownIds = new Set(tasks.value.map(task => task.id))
    const requestedPageSize = reset ? TASK_PAGE_SIZE : Math.max(TASK_PAGE_SIZE, page.value * TASK_PAGE_SIZE)
    const tree = await chatService.tasks(
      props.roomId,
      props.fromMessageId,
      1,
      requestedPageSize,
      props.viewerAgentId,
    )
    if (sequence !== requestSequence) return
    tasks.value = tree.items
    total.value = tree.total
    if (reset) page.value = 1
    error.value = ''
    const scrollForCreatedTask = tree.items.some(task => createdTaskIdsAwaitingRefresh.has(task.id))
    const scrollForNewTask = tree.items.some(task => !knownIds.has(task.id))
    createdTaskIdsAwaitingRefresh.clear()
    if (scrollAfterLoad || scrollForCreatedTask || scrollForNewTask) scrollTasksToBottom()
  } catch (caught) {
    if (sequence === requestSequence) error.value = apiErrorDetail(caught) ?? t('chat.tasksLoadError')
  } finally {
    if (sequence === requestSequence) {
      loading.value = false
      hasCompletedInitialTaskLoad.value = true
    }
  }
}

async function loadOlderTasks(): Promise<void> {
  if (loading.value || loadingOlder.value || !hasOlderTasks.value || !props.fromMessageId) return
  const sequence = requestSequence
  const scrollTarget = taskScrollArea.value?.getScrollTarget()
  const previousHeight = scrollTarget?.scrollHeight ?? 0
  const previousPosition = scrollTarget?.scrollTop ?? 0
  loadingOlder.value = true
  try {
    const nextPage = page.value + 1
    const tree = await chatService.tasks(
      props.roomId,
      props.fromMessageId,
      nextPage,
      TASK_PAGE_SIZE,
      props.viewerAgentId,
    )
    if (sequence !== requestSequence) return
    const knownIds = new Set(tasks.value.map(task => task.id))
    tasks.value = [...tasks.value, ...tree.items.filter(task => !knownIds.has(task.id))]
    total.value = tree.total
    page.value = nextPage
    error.value = ''
    await nextTick()
    await new Promise<void>(resolve => window.requestAnimationFrame(() => resolve()))
    const newHeight = taskScrollArea.value?.getScrollTarget().scrollHeight ?? previousHeight
    taskScrollArea.value?.setScrollPosition('vertical', previousPosition + newHeight - previousHeight, 0)
  } catch (caught) {
    if (sequence === requestSequence) error.value = apiErrorDetail(caught) ?? t('chat.tasksLoadError')
  } finally {
    if (sequence === requestSequence) loadingOlder.value = false
  }
}

function onTaskScroll(info: TaskScrollInfo): void {
  const atBottom = info.verticalSize - info.verticalContainerSize - info.verticalPosition <= TASK_BOTTOM_THRESHOLD
  showScrollToBottom.value = info.verticalSize > info.verticalContainerSize && !atBottom
  if (info.verticalPosition <= 24) void loadOlderTasks()
}

function updateScrollButtonVisibility(): void {
  void nextTick(() => {
    if (scrollVisibilityFrame !== null) window.cancelAnimationFrame(scrollVisibilityFrame)
    scrollVisibilityFrame = window.requestAnimationFrame(() => {
      const scrollTarget = taskScrollArea.value?.getScrollTarget()
      if (scrollTarget) {
        const atBottom = scrollTarget.scrollHeight - scrollTarget.clientHeight - scrollTarget.scrollTop <= TASK_BOTTOM_THRESHOLD
        showScrollToBottom.value = scrollTarget.scrollHeight > scrollTarget.clientHeight && !atBottom
      }
      scrollVisibilityFrame = null
    })
  })
}

function disconnectTaskScrollResizeObserver(): void {
  taskScrollResizeObserver?.disconnect()
  taskScrollResizeObserver = null
}

function observeTaskScrollResize(): void {
  if (taskScrollResizeObserver) return
  const scrollArea = taskScrollArea.value
  if (!scrollArea) return
  taskScrollResizeObserver = new ResizeObserver(() => {
    if (pendingBottomScroll) scrollTasksToBottom()
  })
  taskScrollResizeObserver.observe(scrollArea.$el)
}

function scrollTasksToBottom(): void {
  pendingBottomScroll = true
  showScrollToBottom.value = false
  void nextTick(() => {
    observeTaskScrollResize()
    if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
    scrollFrame = window.requestAnimationFrame(() => {
      const scrollArea = taskScrollArea.value
      const scrollTarget = scrollArea?.getScrollTarget()
      if (!scrollArea || !scrollTarget || scrollArea.$el.clientHeight === 0 || scrollTarget.clientHeight === 0) {
        scrollFrame = null
        return
      }
      scrollArea.setScrollPosition('vertical', scrollTarget.scrollHeight, 0)
      scrollFrame = window.requestAnimationFrame(() => {
        const currentScrollArea = taskScrollArea.value
        const currentScrollTarget = currentScrollArea?.getScrollTarget()
        if (currentScrollArea && currentScrollTarget) {
          currentScrollArea.setScrollPosition('vertical', currentScrollTarget.scrollHeight, 0)
          pendingBottomScroll = false
          disconnectTaskScrollResizeObserver()
          updateScrollButtonVisibility()
        }
        scrollFrame = null
      })
    })
  })
}

defineExpose({ scrollToBottom: scrollTasksToBottom })

function scheduleRefresh(): void {
  if (!props.canRead) return
  if (refreshTimer) window.clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => { void load(false) }, 250)
}

function applyTaskEventSnapshot(event: TaskSnapshotEvent): void {
  if (event.data) {
    taskStore.applyTaskSnapshot(event.data)
    tasks.value = tasks.value.map(task => task.id === event.data!.id
      ? { ...task, ...event.data, tree_parent_id: task.tree_parent_id, directly_linked: task.directly_linked }
      : task)
  }
}

function onTaskCreate(event: TaskSnapshotEvent): void {
  applyTaskEventSnapshot(event)
  if (event.data) createdTaskIdsAwaitingRefresh.add(event.data.id)
  scheduleRefresh()
}

function onTaskUpdate(event: TaskSnapshotEvent): void {
  applyTaskEventSnapshot(event)
  scheduleRefresh()
}

function onTaskDelete(event: TaskDeleteEvent): void {
  const id = event.data?.id
  if (id) {
    tasks.value = tasks.value.filter(task => task.id !== id)
    delete taskExpansionOverrides.value[id]
    if (selectedTaskId.value === id) detailDialogOpen.value = false
  }
  scheduleRefresh()
}

function onTaskMutation(): void { scheduleRefresh() }
function onConnect(): void { void load(false) }

function subscribe(): void {
  if (subscribed) return
  websocket.createWebsocket()
  websocket.onEvent('task', 'create', onTaskCreate)
  websocket.onEvent('task', 'update', onTaskUpdate)
  websocket.onEvent('task', 'delete', onTaskDelete)
  websocket.onEvent('task', 'restore', onTaskMutation)
  websocket.onEvent('task', 'cleanup', onTaskMutation)
  websocket.onConnect(onConnect)
  subscribed = true
}

function unsubscribe(): void {
  if (!subscribed) return
  websocket.offEvent('task', 'create', onTaskCreate)
  websocket.offEvent('task', 'update', onTaskUpdate)
  websocket.offEvent('task', 'delete', onTaskDelete)
  websocket.offEvent('task', 'restore', onTaskMutation)
  websocket.offEvent('task', 'cleanup', onTaskMutation)
  websocket.offConnect(onConnect)
  subscribed = false
}

function openTask(taskId: string): void {
  selectedTaskId.value = taskId
  detailDialogOpen.value = true
}

function refreshTaskDetail(): void {
  // TaskDetail owns its detailed refresh lifecycle; the tree reconciles independently.
}

function confirmTaskDelete(task: Task): void {
  showConfirmationDialog({
    title: t('task.deleteConfirm'),
    message: `${t('task.deleteMessage', { label: task.label })}\n${t('task.deleteReversible')}`,
    cancel: true,
    focus: 'cancel',
  }).onOk(() => {
    void deleteTask(task)
  })
}

async function deleteTask(task: Task): Promise<void> {
  if (!canEdit.value || taskAction(task.id)) return
  pendingTaskActions.value[task.id] = 'delete'
  try {
    await taskStore.deleteTask(task.id)
    tasks.value = tasks.value.filter(item => item.id !== task.id)
    if (selectedTaskId.value === task.id) {
      detailDialogOpen.value = false
      selectedTaskId.value = null
    }
    $q.notify({ type: 'positive', message: t('task.notify.deleted') })
    scheduleRefresh()
  } catch (caught) {
    $q.notify({ type: 'negative', message: apiErrorDetail(caught) ?? t('task.notify.deleteError') })
  } finally {
    delete pendingTaskActions.value[task.id]
  }
}

watch(
  () => [props.roomId, props.fromMessageId, props.viewerAgentId, props.canRead] as const,
  ([, , , canRead]) => {
    detailDialogOpen.value = false
    selectedTaskId.value = null
    taskExpansionOverrides.value = {}
    createdTaskIdsAwaitingRefresh.clear()
    showScrollToBottom.value = false
    if (canRead) {
      subscribe()
      void loadAgentNames()
    }
    else unsubscribe()
    page.value = 1
    void load(true, true)
  },
  { immediate: true },
)
watch(tasks, () => {
  updateScrollButtonVisibility()
}, { flush: 'post' })
watch(() => tasks.value.map(task => task.topic_id), ids => { void resolveTopicRefs(ids) }, { immediate: true })

onBeforeUnmount(() => {
  requestSequence += 1
  if (refreshTimer) window.clearTimeout(refreshTimer)
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
  if (scrollVisibilityFrame !== null) window.cancelAnimationFrame(scrollVisibilityFrame)
  disconnectTaskScrollResizeObserver()
  unsubscribe()
})
</script>

<style scoped>
.agent-tasks-panel { display: flex; width: 100%; min-width: 0; max-width: 100%; flex: 1 1 auto; flex-direction: column; min-height: 0; overflow-x: hidden; color: var(--chat-text, #252b36); background: var(--chat-surface, #fff); }
.agent-tasks-toolbar { flex: 0 0 auto; min-height: 58px; padding: 0 8px 0 12px; }
.agent-tasks-title { min-width: 0; color: var(--chat-text-secondary, #344054); font-size: .9rem; font-weight: 600; line-height: 1.15; }
.agent-tasks-count { margin-top: 2px; color: var(--chat-task-text-subtle, #667085); font-size: .73rem; font-weight: 400; }
.agent-tasks-live { flex: 0 0 auto; padding: 2px 5px; font-size: .68rem; font-weight: 500; }
.agent-tasks-scroll-zone { position: relative; display: flex; width: 100%; min-width: 0; flex: 1 1 auto; min-height: 0; }
.agent-tasks-scroll { width: 100%; min-width: 0; max-width: 100%; flex: 1 1 auto; min-height: 0; overflow-x: hidden; }
.agent-tasks-scroll :deep(.q-scrollarea__container),
.agent-tasks-scroll :deep(.q-scrollarea__content) { width: 100%; min-width: 0 !important; max-width: 100%; overflow-x: hidden; }
.agent-tasks-scroll :deep(.q-scrollarea__bar--h),
.agent-tasks-scroll :deep(.q-scrollarea__thumb--h) { display: none; }
.agent-tasks-state { display: flex; min-height: 170px; align-items: center; justify-content: center; flex-direction: column; gap: 8px; padding: 20px; text-align: center; font-size: .78rem; }
.agent-task-list { position: relative; width: 100%; min-width: 0; max-width: 100%; padding: 3px 0; overflow-x: hidden; }
.agent-tasks-load-older { position: absolute; top: 5px; left: 50%; z-index: 2; display: flex; align-items: center; justify-content: center; transform: translateX(-50%); pointer-events: none; }
.agent-task-row { --chat-task-font-size: .875rem; box-sizing: border-box; width: 100%; min-width: 0; max-width: 100%; min-height: 64px; padding-top: 7px; padding-right: 8px; padding-bottom: 7px; overflow: hidden; border-left: 3px solid transparent; border-bottom: 1px solid var(--chat-border, rgba(35, 46, 66, .065)); font-size: var(--chat-task-font-size); }
.agent-task-row:hover { background: var(--chat-surface-hover, #f7f8fa); }
.agent-task-row--collapsed { min-height: 0; padding-top: 2px; padding-bottom: 2px; }
.agent-task-row--error { border-left-color: var(--q-negative); background: var(--chat-danger-soft, rgba(193, 0, 21, .035)); }
.agent-task-main { min-width: 0; max-width: 100%; overflow: hidden; }
.agent-task-header { display: grid; min-width: 0; grid-template-columns: 42px minmax(0, 1fr); align-items: start; column-gap: 7px; }
.agent-task-header--collapsed { grid-template-columns: minmax(0, 1fr); }
.agent-task-avatar { position: relative; width: 42px; height: 42px; }
.agent-task-status-dot { position: absolute; right: -3px; bottom: -3px; display: flex; width: 18px; height: 18px; align-items: center; justify-content: center; border-radius: 50%; background: var(--chat-surface, #fff); box-shadow: 0 0 0 1px var(--chat-border-strong, rgba(35, 46, 66, .12)); }
.agent-task-heading { min-width: 0; }
.agent-task-title-row { display: flex; min-width: 0; align-items: flex-start; gap: 3px; }
.agent-task-expansion-toggle { display: flex; min-width: 0; flex: 1 1 auto; align-items: flex-start; gap: 2px; padding: 2px 0; border: 0; border-radius: 3px; color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer; }
.agent-task-expansion-toggle:focus-visible { outline: 2px solid var(--q-primary); outline-offset: 1px; }
.agent-task-expansion-toggle > .q-icon { flex: 0 0 auto; margin-top: -1px; color: var(--chat-task-text-subtle, #667085); }
.agent-task-label { flex: 1 1 auto; min-width: 0; color: var(--chat-text, #273142); font-size: var(--chat-task-font-size); font-weight: 700; line-height: 1.25; overflow-wrap: anywhere; word-break: break-word; white-space: normal; }
.agent-task-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 1px; margin: -3px -2px 0 1px; }
.agent-task-action { min-width: 24px; min-height: 24px; }
.agent-task-pause-icon { flex: 0 0 auto; margin-top: 1px; }
.agent-task-details { flex: 0 0 auto; min-height: 25px; padding: 0 4px; font-size: .72rem; }
.agent-task-previous-operations { margin-top: 2px; }
.agent-task-operations { margin-top: 6px; }
.agent-task-objective { display: flex; min-width: 0; align-items: flex-start; gap: 4px; margin-top: 4px; padding-top: 3px; border-top: 1px solid var(--chat-border, rgba(35, 46, 66, .08)); color: var(--chat-task-text-muted, #475467); font-size: var(--chat-task-font-size); line-height: 1.25; overflow-wrap: anywhere; word-break: break-word; }
.agent-task-objective-icon { flex: 0 0 auto; margin-top: 1px; color: var(--chat-task-text-subtle, #667085); }
.agent-task-meta { display: flex; min-width: 0; max-width: 100%; flex-wrap: wrap; align-items: center; gap: 5px; margin-top: 4px; color: var(--chat-task-text-subtle, #667085); font-size: var(--chat-task-font-size); line-height: 1.1; overflow-wrap: anywhere; }
.agent-task-topic { min-width: 0; max-width: 100%; }
.agent-tasks-panel--embedded .agent-task-actions { flex-wrap: wrap; justify-content: flex-end; }
.agent-tasks-inline-error { padding: 6px 9px; font-size: .75rem; }
.scroll-to-bottom-button { position: absolute; right: 14px; bottom: 12px; z-index: 2; color: var(--chat-text-muted); background: color-mix(in srgb, var(--chat-surface-raised) 88%, transparent); border: 1px solid var(--chat-border-strong); box-shadow: 0 2px 8px color-mix(in srgb, var(--chat-shadow) 70%, transparent); opacity: .78; backdrop-filter: blur(5px); transition: color .15s ease, opacity .15s ease, background-color .15s ease; }
.scroll-to-bottom-button:hover,
.scroll-to-bottom-button:focus-visible { color: var(--q-primary); background: var(--chat-surface-raised); opacity: 1; }
.scroll-to-bottom-enter-active,
.scroll-to-bottom-leave-active { transition: opacity .15s ease, transform .15s ease; }
.scroll-to-bottom-enter-from,
.scroll-to-bottom-leave-to { opacity: 0; transform: translateY(6px); }
.task-detail-dialog { display: flex; width: min(96vw, 1500px); height: calc(100vh - 32px); max-width: 1500px; flex-direction: column; }
.task-detail-content { flex: 1; overflow: auto; padding: 0; }
</style>
