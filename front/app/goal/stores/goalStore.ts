import { computed, ref, watch, onScopeDispose } from 'vue'
import { defineStore } from 'pinia'
import { websocket } from '@/core/websocket'
import { useAuthStore } from '@/core/user/stores/authStore'
import { goalService } from '../services/goalService'
import { sessionGeneration } from '@/core/api'
import type {
  Goal,
  GoalCreate,
  GoalCycle,
  GoalDetail,
  GoalSettings,
  GoalSettingsUpdate,
  GoalStatus,
  GoalSummary,
  GoalTreeNode,
  GoalUpdate,
} from '../types'

const EMPTY_SUMMARY: GoalSummary = {
  active: 0,
  paused: 0,
  completed: 0,
  errors: 0,
  total_cost: 0,
}

function mergeGoalSnapshot(current: Goal, incoming: Goal): Goal {
  if (incoming.revision < current.revision) return current
  Object.assign(current, incoming)
  return current
}

function reconcileGoalList(current: Goal[], incoming: Goal[]): Goal[] {
  const currentById = new Map(current.map(goal => [goal.id, goal]))
  return incoming.map((goal) => {
    const existing = currentById.get(goal.id)
    return existing ? mergeGoalSnapshot(existing, goal) : goal
  })
}

export const useGoalStore = defineStore('goal', () => {
  const goals = ref<Goal[]>([])
  const currentGoal = ref<GoalDetail | null>(null)
  const treeGoals = ref<GoalTreeNode[]>([])
  const cycles = ref<GoalCycle[]>([])
  const loading = ref(false)
  const detailLoading = ref(false)
  const cyclesLoading = ref(false)
  const error = ref<unknown>(null)
  const page = ref(0)
  const pageSize = ref(50)
  const total = ref(0)
  const cyclePage = ref(1)
  const cyclePageSize = ref(50)
  const cycleTotal = ref(0)
  const trackingLlmConfigured = ref<boolean | null>(null)
  const settings = ref<GoalSettings | null>(null)
  const settingsLoading = ref(false)
  const settingsSaving = ref(false)
  const summary = ref<GoalSummary>({ ...EMPTY_SUMMARY })
  const agentFilter = ref<number | null>(null)
  const statusFilter = ref<GoalStatus | null>(null)
  const search = ref('')
  const isSubscribed = ref(false)
  const unwatchAuth = ref<(() => void) | null>(null)
  let refreshTimer: ReturnType<typeof setTimeout> | null = null
  const requests = { list: 0, tree: 0, detail: 0, cycles: 0 }
  function beginRequest(kind: keyof typeof requests): () => boolean {
    const request = ++requests[kind]
    const session = sessionGeneration()
    return () => request === requests[kind] && session === sessionGeneration()
  }

  function clearSelection(): void {
    requests.detail++
    requests.cycles++
    currentGoal.value = null
    cycles.value = []
    cycleTotal.value = 0
    detailLoading.value = false
    cyclesLoading.value = false
  }

  const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const cyclePageCount = computed(() => (
    Math.max(1, Math.ceil(cycleTotal.value / cyclePageSize.value))
  ))

  async function fetchSettings(): Promise<GoalSettings> {
    if (settings.value === null) settingsLoading.value = true
    try {
      settings.value = await goalService.getSettings()
      return settings.value
    } catch (caught) {
      console.error('Error fetching Goal settings:', caught)
      throw caught
    } finally {
      settingsLoading.value = false
    }
  }

  async function updateSettings(data: GoalSettingsUpdate): Promise<GoalSettings> {
    settingsSaving.value = true
    try {
      settings.value = await goalService.updateSettings(data)
      return settings.value
    } catch (caught) {
      console.error('Error updating Goal settings:', caught)
      throw caught
    } finally {
      settingsSaving.value = false
    }
  }

  async function fetchGoals(targetPage?: number): Promise<void> {
    const current = beginRequest('list')
    if (targetPage !== undefined) page.value = targetPage
    loading.value = true
    error.value = null
    try {
      const result = await goalService.list({
        skip: page.value * pageSize.value,
        limit: pageSize.value,
        agentId: agentFilter.value,
        status: statusFilter.value,
        search: search.value,
      })
      if (!current()) return
      if (!result.items.length && page.value > 0) {
        page.value -= 1
        await fetchGoals(page.value)
        return
      }
      goals.value = reconcileGoalList(goals.value, result.items)
      total.value = result.total
      summary.value = result.summary
      trackingLlmConfigured.value = result.tracking_llm_configured
    } catch (caught) {
      if (!current()) return
      error.value = caught
      console.error('Error fetching goals:', caught)
      throw caught
    } finally {
      if (current()) loading.value = false
    }
  }

  async function fetchTree(): Promise<void> {
    const current = beginRequest('tree')
    const result = await goalService.tree()
    if (current()) treeGoals.value = result.items
  }

  async function fetchCycles(id: string, targetPage?: number): Promise<void> {
    const current = beginRequest('cycles')
    if (targetPage !== undefined) cyclePage.value = targetPage
    cyclesLoading.value = true
    try {
      const result = await goalService.listCycles(id, {
        page: cyclePage.value,
        pageSize: cyclePageSize.value,
      })
      if (!current()) return
      if (!result.items.length && result.total > 0 && cyclePage.value > 1) {
        cyclePage.value -= 1
        await fetchCycles(id, cyclePage.value)
        return
      }
      cycles.value = result.items
      cycleTotal.value = result.total
      cyclePage.value = result.page
      cyclePageSize.value = result.page_size
    } finally {
      if (current()) cyclesLoading.value = false
    }
  }

  async function fetchGoal(id: string, targetCyclePage?: number): Promise<GoalDetail | null> {
    const current = beginRequest('detail')
    requests.cycles++
    detailLoading.value = true
    try {
      const previousGoal = currentGoal.value
      const fetchedGoal = await goalService.get(id)
      if (!current()) return null
      currentGoal.value = previousGoal?.id === id
        ? mergeGoalSnapshot(previousGoal, fetchedGoal)
        : fetchedGoal
      await fetchCycles(
        id,
        targetCyclePage ?? (previousGoal?.id === id ? cyclePage.value : 1),
      )
      return current() ? currentGoal.value : null
    } catch (caught) {
      if (!current()) return null
      throw caught
    } finally {
      if (current()) detailLoading.value = false
    }
  }

  function replaceGoal(goal: Goal): void {
    const index = goals.value.findIndex(item => item.id === goal.id)
    if (index >= 0) mergeGoalSnapshot(goals.value[index], goal)
    if (currentGoal.value?.id === goal.id) {
      mergeGoalSnapshot(currentGoal.value, goal)
    }
  }

  async function createGoal(data: GoalCreate): Promise<Goal> {
    const goal = await goalService.create(data)
    await Promise.all([fetchGoals(0), fetchTree()])
    return goal
  }

  async function updateGoal(id: string, data: GoalUpdate): Promise<Goal> {
    const goal = await goalService.update(id, data)
    replaceGoal(goal)
    scheduleRefresh()
    await fetchTree()
    return goal
  }

  async function command(
    action: 'pause' | 'resume' | 'complete' | 'runNow',
    goal: Goal,
  ): Promise<Goal> {
    const updated = await goalService[action](goal.id, { expected_revision: goal.revision })
    replaceGoal(updated)
    scheduleRefresh()
    await fetchTree()
    return updated
  }

  async function deleteGoal(id: string): Promise<void> {
    await goalService.delete(id)
    goals.value = goals.value.filter(goal => goal.id !== id)
    if (currentGoal.value?.id === id) {
      currentGoal.value = null
      cycles.value = []
      cycleTotal.value = 0
      cyclePage.value = 1
    }
    await fetchTree()
    scheduleRefresh()
  }

  function scheduleRefresh(): void {
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => {
      void fetchGoals()
      void fetchTree()
      if (currentGoal.value) void fetchGoal(currentGoal.value.id)
    }, 300)
  }

  function onGoalCreate(): void {
    scheduleRefresh()
  }

  function onGoalUpdate(response: { data: Goal }): void {
    replaceGoal(response.data)
    scheduleRefresh()
  }

  function onGoalDelete(response: { data: { id: string } }): void {
    goals.value = goals.value.filter(goal => goal.id !== response.data.id)
    if (currentGoal.value?.id === response.data.id) {
      currentGoal.value = null
      cycles.value = []
      cycleTotal.value = 0
      cyclePage.value = 1
    }
    scheduleRefresh()
  }

  function onTaskUpdate(response: { data: { goal_id?: string | null } }): void {
    if (response.data.goal_id) scheduleRefresh()
  }

  function onSettingsUpdate(response: { data: GoalSettings }): void {
    settings.value = response.data
  }

  function subscribe(): void {
    if (isSubscribed.value) return
    const authStore = useAuthStore()
    if (!authStore.user?.id) {
      if (unwatchAuth.value) unwatchAuth.value()
      unwatchAuth.value = watch(
        () => authStore.user?.id,
        userId => {
          if (userId && !isSubscribed.value) doSubscribe()
        },
        { immediate: true },
      )
      return
    }
    doSubscribe()
  }

  function doSubscribe(): void {
    if (isSubscribed.value) return
    websocket.createWebsocket()
    websocket.onEvent('goal', 'create', onGoalCreate)
    websocket.onEvent('goal', 'update', onGoalUpdate)
    websocket.onEvent('goal', 'delete', onGoalDelete)
    websocket.onEvent('task', 'update', onTaskUpdate)
    websocket.onEvent('goal_settings', 'update', onSettingsUpdate)
    isSubscribed.value = true
  }

  function unsubscribe(): void {
    requests.list++
    requests.tree++
    clearSelection()
    loading.value = false
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = null
    if (unwatchAuth.value) {
      unwatchAuth.value()
      unwatchAuth.value = null
    }
    if (!isSubscribed.value) return
    websocket.offEvent('goal', 'create', onGoalCreate)
    websocket.offEvent('goal', 'update', onGoalUpdate)
    websocket.offEvent('goal', 'delete', onGoalDelete)
    websocket.offEvent('task', 'update', onTaskUpdate)
    websocket.offEvent('goal_settings', 'update', onSettingsUpdate)
    isSubscribed.value = false
  }

  onScopeDispose(unsubscribe)

  return {
    goals,
    currentGoal,
    clearSelection,
    treeGoals,
    cycles,
    loading,
    detailLoading,
    cyclesLoading,
    error,
    page,
    pageSize,
    pageCount,
    total,
    cyclePage,
    cyclePageSize,
    cyclePageCount,
    cycleTotal,
    trackingLlmConfigured,
    settings,
    settingsLoading,
    settingsSaving,
    summary,
    agentFilter,
    statusFilter,
    search,
    fetchSettings,
    updateSettings,
    fetchGoals,
    fetchTree,
    fetchGoal,
    fetchCycles,
    createGoal,
    updateGoal,
    command,
    deleteGoal,
    subscribe,
    unsubscribe,
  }
})
