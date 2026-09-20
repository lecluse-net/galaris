import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { taskService } from '../services/taskService'
import type { AIResult, Task, TaskCreate, TaskOverview, TaskUpdate } from '../types'
import type { Agent } from '@/app/agent/services/agentService'
import { websocket } from '@/core/websocket'
import { useAuthStore } from '@/core/user/stores/authStore'
import { mergeTaskSnapshot } from '../taskSnapshot'
import {
  applyTaskLiveRunEvent,
  reconcileTaskAIResult,
  taskRunId,
  type TaskLiveRunEvent,
  type TaskLiveRunState,
} from '../aiResult'

const RECENT_PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 500]

export const useTaskStore = defineStore('task', () => {
  // State
  const currentTask = ref<Task | null>(null)
  const currentTaskAgent = ref<Agent | null>(null)
  const loading = ref(false)
  // Paginated tasks ordered by created_at descending.
  const recentTasks   = ref<Task[]>([])
  const recentPage    = ref(0)
  const recentPageSize = ref(50)
  const recentTotal = ref(0)
  const recentHasMore = ref(false)
  const recentLoading = ref(false)
  const recentSearchQuery = ref('')
  const recentErrorsOnly = ref(false)
  const recentPausedOnly = ref(false)
  const recentRunningOnly = ref(false)
  const recentDateFrom = ref<string | null>(null)
  const recentDateTo = ref<string | null>(null)
  const recentTopicFilter = ref<string | null>(null)
  const recentSummary = ref<TaskOverview>({
    running: 0,
    completed: 0,
    paused: 0,
    errors: 0,
  })
  let   recentTimer: ReturnType<typeof setTimeout> | null = null
  // Filter by agent.
  const selectedAgentFilter = ref<number | null>(null)
  // WebSocket subscription state
  const isSubscribed = ref(false)
  const unwatchAuth = ref<(() => void) | null>(null)
  const latestTaskUpdate = ref<Task | null>(null)
  const liveTaskRuns = ref<Record<string, TaskLiveRunState>>({})
  let currentTaskRequest = 0
  let recentRequest = 0
  const recentPageCount = computed(() => Math.max(1, Math.ceil(recentTotal.value / recentPageSize.value)))

  // Actions
  async function fetchTaskById(id: string) {
    const request = ++currentTaskRequest
    loading.value = true
    try {
      const task = await taskService.getById(id)
      if (request === currentTaskRequest) {
        const latest = latestTaskUpdate.value?.id === id ? latestTaskUpdate.value : null
        const reconciled = latest ? mergeTaskSnapshot(task, latest) : task
        currentTask.value = mergeTaskSnapshot(
          currentTask.value?.id === id ? currentTask.value : null,
          reconciled,
        )
        currentTaskAgent.value = null
      }
      return task
    } finally {
      if (request === currentTaskRequest) loading.value = false
    }
  }

  async function fetchTaskByIdWithAgent(id: string) {
    const request = ++currentTaskRequest
    loading.value = true
    try {
      const { task, agent } = await taskService.getByIdWithAgent(id)
      if (request === currentTaskRequest) {
        const latest = latestTaskUpdate.value?.id === id ? latestTaskUpdate.value : null
        const reconciled = latest ? mergeTaskSnapshot(task, latest) : task
        currentTask.value = mergeTaskSnapshot(
          currentTask.value?.id === id ? currentTask.value : null,
          reconciled,
        )
        currentTaskAgent.value = agent || null
      }
      return { task, agent }
    } finally {
      if (request === currentTaskRequest) loading.value = false
    }
  }

  function applyTaskSnapshot(snapshot: Task): Task {
    latestTaskUpdate.value = mergeTaskSnapshot(
      latestTaskUpdate.value?.id === snapshot.id ? latestTaskUpdate.value : null,
      snapshot,
    )
    if (currentTask.value?.id === snapshot.id) {
      currentTask.value = mergeTaskSnapshot(currentTask.value, snapshot)
      reconcileTaskLiveRun(currentTask.value)
      return currentTask.value
    }
    reconcileTaskLiveRun(snapshot)
    return snapshot
  }

  function reconcileTaskLiveRun(snapshot: Task): void {
    const current = liveTaskRuns.value[snapshot.id]
    if (!current) return

    const expectedRunId = taskRunId(snapshot)
    if (expectedRunId && current.runId !== expectedRunId) {
      const next = { ...liveTaskRuns.value }
      delete next[snapshot.id]
      liveTaskRuns.value = next
      return
    }

    const durableResult = snapshot.execution_result ?? null
    if (!durableResult) return
    liveTaskRuns.value = {
      ...liveTaskRuns.value,
      [snapshot.id]: {
        ...current,
        result: reconcileTaskAIResult(snapshot, current.result) ?? current.result,
      },
    }
  }

  function applyLiveRunEvent(event: TaskLiveRunEvent, task: Task | null): AIResult | null {
    const current = liveTaskRuns.value[event.task_id] ?? null
    const next = applyTaskLiveRunEvent(
      current,
      event,
      task?.id === event.task_id ? task.execution_result ?? null : null,
      task?.id === event.task_id ? taskRunId(task) : null,
    )
    if (!next || next === current) return current?.result ?? null
    liveTaskRuns.value = { ...liveTaskRuns.value, [event.task_id]: next }
    return next.result
  }

  function dropLiveTaskRun(taskId: string): void {
    if (!liveTaskRuns.value[taskId]) return
    const next = { ...liveTaskRuns.value }
    delete next[taskId]
    liveTaskRuns.value = next
  }

  async function createTask(data: TaskCreate): Promise<Task> {
    const newTask = await taskService.create(data)
    return newTask
  }

  async function updateTask(id: string, data: TaskUpdate): Promise<Task> {
    const updated = await taskService.update(id, data)
    applyTaskSnapshot(updated)
    return updated
  }

  async function deleteTask(id: string): Promise<void> {
    await taskService.delete(id)
    recentTasks.value = recentTasks.value.filter(t => t.id !== id)
    dropLiveTaskRun(id)
    if (currentTask.value?.id === id) {
      currentTask.value = null
    }
  }

  async function restoreTask(id: string): Promise<Task> {
      return taskService.restore(id)
  }

  async function runTask(id: string): Promise<Task> {
      const task = await taskService.run(id)
      applyTaskSnapshot(task)
      scheduleRecentRefresh()
      return task
  }

  async function pauseTask(id: string): Promise<Task> {
      const task = await taskService.pause(id)
      applyTaskSnapshot(task)
      scheduleRecentRefresh()
      return task
  }

  async function resumeTask(id: string): Promise<Task> {
      const task = await taskService.resume(id)
      applyTaskSnapshot(task)
      scheduleRecentRefresh()
      return task
  }

  async function forceTerminateTask(id: string, expectedRevision: number): Promise<Task> {
      const task = await taskService.forceTerminate(id, expectedRevision)
      applyTaskSnapshot(task)
      scheduleRecentRefresh()
      return task
  }

  async function retryTask(id: string, expectedRevision: number): Promise<Task> {
      const task = await taskService.retry(id, expectedRevision)
      applyTaskSnapshot(task)
      scheduleRecentRefresh()
      return task
  }

  /** Delete processed tasks without affecting active tasks. */
  async function cleanupTasks(): Promise<void> {
    await taskService.cleanup()
    await fetchRecentTasks(0)
    currentTask.value = null
    currentTaskAgent.value = null
  }

  async function fetchRecentTasks(page?: number): Promise<void> {
    if (page !== undefined) recentPage.value = page
    const request = ++recentRequest
    recentLoading.value = true
    try {
      const result = await taskService.getRecent(
        recentPage.value * recentPageSize.value,
        recentPageSize.value,
        selectedAgentFilter.value ?? undefined,
        recentSearchQuery.value,
        recentErrorsOnly.value,
        recentPausedOnly.value,
        recentDateFrom.value,
        recentDateTo.value,
        recentRunningOnly.value ? true : undefined,
        recentTopicFilter.value,
      )
      if (request !== recentRequest) return
      if (result.items.length === 0 && recentPage.value > 0) {
        recentPage.value -= 1
        await fetchRecentTasks(recentPage.value)
        return
      }
      if (request === recentRequest) {
        recentTotal.value = result.total
        recentSummary.value = result.summary
        recentHasMore.value = (recentPage.value + 1) < recentPageCount.value
        recentTasks.value = result.items.map((task) => {
          const live = latestTaskUpdate.value?.id === task.id ? latestTaskUpdate.value : null
          return live ? mergeTaskSnapshot(task, live) : task
        })
      }
    } finally {
      if (request === recentRequest) recentLoading.value = false
    }
  }

  function setRecentPageSize(size: number): void {
    recentPageSize.value = size
    void fetchRecentTasks(0)
  }

  function setRecentSearchQuery(query: string): void {
    recentSearchQuery.value = query
    void fetchRecentTasks(0)
  }

  function setRecentErrorsOnly(value: boolean): void {
    recentErrorsOnly.value = value
    if (value) {
      recentPausedOnly.value = false
      recentRunningOnly.value = false
    }
    void fetchRecentTasks(0)
  }

  function setRecentPausedOnly(value: boolean): void {
    recentPausedOnly.value = value
    if (value) {
      recentErrorsOnly.value = false
      recentRunningOnly.value = false
    }
    void fetchRecentTasks(0)
  }

  function setRecentRunningOnly(value: boolean): void {
    recentRunningOnly.value = value
    if (value) {
      recentErrorsOnly.value = false
      recentPausedOnly.value = false
    }
    void fetchRecentTasks(0)
  }

  function setRecentDateRange(dateFrom: string | null, dateTo: string | null): void {
    recentDateFrom.value = dateFrom
    recentDateTo.value = dateTo
    void fetchRecentTasks(0)
  }

  function setRecentTopicFilter(topicId: string | null): void {
    recentTopicFilter.value = topicId
    void fetchRecentTasks(0)
  }

  function scheduleRecentRefresh(): void {
    if (recentTimer) clearTimeout(recentTimer)
    recentTimer = setTimeout(() => fetchRecentTasks(), 300)
  }

  function reconcileAfterConnect(): void {
    scheduleRecentRefresh()
    const taskId = currentTask.value?.id
    if (taskId) {
      void taskService.getById(taskId)
        .then((task) => applyTaskSnapshot(task))
        .catch((error: unknown) => {
          console.warn('Failed to reconcile task after WebSocket reconnect:', error)
        })
    }
  }

  const onTaskCreate = () => scheduleRecentRefresh()
  const onTaskUpdate = (response: { data: Task }) => {
    const updatedData = response.data
    applyTaskSnapshot(updatedData)
    recentTasks.value = recentTasks.value.map((task) => (
      task.id === updatedData.id ? mergeTaskSnapshot(task, updatedData) : task
    ))
    scheduleRecentRefresh()
  }
  const onTaskDelete = (response: { data: { id: string } }) => {
    const deletedId = response.data.id
    recentTasks.value = recentTasks.value.filter(task => task.id !== deletedId)
    dropLiveTaskRun(deletedId)
    if (currentTask.value?.id === deletedId) currentTask.value = null
    scheduleRecentRefresh()
  }
  const onTaskRestore = () => scheduleRecentRefresh()
  const onTaskCleanup = () => {
    recentTasks.value = []
    currentTask.value = null
    currentTaskAgent.value = null
    latestTaskUpdate.value = null
    liveTaskRuns.value = {}
    scheduleRecentRefresh()
  }

  /**
   * Subscribe to global task WebSocket events emitted by the backend.
   */
  function subscribeToTasks() {
    if (isSubscribed.value) return

    const authStore = useAuthStore()
    const userId = authStore.user?.id

    if (!userId) {
      if (unwatchAuth.value) unwatchAuth.value()
      unwatchAuth.value = watch(
        () => authStore.user?.id,
        (newUserId) => {
          if (newUserId && !isSubscribed.value) _doSubscribe()
        },
        { immediate: true }
      )
      return
    }

    _doSubscribe()
  }

  function _doSubscribe() {
    if (isSubscribed.value) return

    websocket.createWebsocket()

    // Refresh the list after any task event, with throttling.
    websocket.onEvent('task', 'create', onTaskCreate)
    websocket.onEvent('task', 'update', onTaskUpdate)
    websocket.onEvent('task', 'delete', onTaskDelete)
    websocket.onEvent('task', 'restore', onTaskRestore)
    websocket.onEvent('task', 'cleanup', onTaskCleanup)
    websocket.onConnect(reconcileAfterConnect)

    isSubscribed.value = true
  }

  function unsubscribeFromTasks() {
    if (unwatchAuth.value) {
      unwatchAuth.value()
      unwatchAuth.value = null
    }
    if (!isSubscribed.value) return

    websocket.offEvent('task', 'create', onTaskCreate)
    websocket.offEvent('task', 'update', onTaskUpdate)
    websocket.offEvent('task', 'delete', onTaskDelete)
    websocket.offEvent('task', 'restore', onTaskRestore)
    websocket.offEvent('task', 'cleanup', onTaskCleanup)
    websocket.offConnect(reconcileAfterConnect)

    isSubscribed.value = false
  }

  return {
    // State
    currentTask,
    currentTaskAgent,
    loading,
    recentTasks,
    recentPage,
    recentPageSize,
    recentTotal,
    recentPageCount,
    recentPageSizeOptions: RECENT_PAGE_SIZE_OPTIONS,
    recentHasMore,
    recentLoading,
    recentSearchQuery,
    recentErrorsOnly,
    recentPausedOnly,
    recentRunningOnly,
    recentDateFrom,
    recentDateTo,
    recentTopicFilter,
    recentSummary,
    selectedAgentFilter,
    isSubscribed,
    latestTaskUpdate,
    liveTaskRuns,
    // Actions
    fetchRecentTasks,
    fetchTaskById,
    fetchTaskByIdWithAgent,
    createTask,
    updateTask,
    deleteTask,
    restoreTask,
    runTask,
    pauseTask,
    resumeTask,
    forceTerminateTask,
    retryTask,
    applyTaskSnapshot,
    applyLiveRunEvent,
    cleanupTasks,
    setRecentPageSize,
    setRecentSearchQuery,
    setRecentErrorsOnly,
    setRecentPausedOnly,
    setRecentRunningOnly,
    setRecentDateRange,
    setRecentTopicFilter,
    subscribeToTasks,
    unsubscribeFromTasks
  }
})
