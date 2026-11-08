import { computed, ref, watch, onScopeDispose } from 'vue'
import { defineStore } from 'pinia'
import { websocket } from '@/core/websocket'
import { useAuthStore } from '@/core/user/stores/authStore'
import { goalService } from '../services/goalService'
import { privileges, usePrivilegeStore } from '@/core/authorize'
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

/** Shared behavior with isolated state for a modal opened from another resource. */
export function createGoalState() {
  const goals = ref<Goal[]>([])
  const currentGoal = ref<GoalDetail | null>(null)
  const treeGoals = ref<GoalTreeNode[]>([])
  const cycles = ref<GoalCycle[]>([])
  const loading = ref(false)
  const detailLoading = ref(false)
  const cyclesLoading = ref(false)
  const cyclesActive = ref(false)
  const listActive = ref(true)
  const detailError = ref<unknown>(null)
  const cyclesError = ref<unknown>(null)
  const treeError = ref<unknown>(null)
  const settingsError = ref<unknown>(null)
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
  const categoryFilter = ref<number | 'none' | null>(null)
  const sortBy = ref<'agent' | 'title' | null>(null)
  const sortDescending = ref(false)
  const search = ref('')
  const isSubscribed = ref(false)
  const unwatchAuth = ref<(() => void) | null>(null)
  let refreshTimer: ReturnType<typeof setTimeout> | null = null
  let refreshRunning = false
  let refreshGeneration = 0
  type Refresh = { list: boolean; tree: boolean; detail: boolean; cycles: boolean }
  let pendingRefresh: Refresh = { list: false, tree: false, detail: false, cycles: false }
  const requests = { list: 0, tree: 0, detail: 0, cycles: 0, settings: 0 }
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
    cyclesActive.value = false
    detailError.value = null
    cyclesError.value = null
    cyclePage.value = 1
  }

  const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const cyclePageCount = computed(() => (
    Math.max(1, Math.ceil(cycleTotal.value / cyclePageSize.value))
  ))

  async function fetchSettings(): Promise<GoalSettings> {
    const current = beginRequest('settings')
    if (settings.value === null) settingsLoading.value = true
    settingsError.value = null
    try {
      const result = await goalService.getSettings(usePrivilegeStore().hasAnyPrivilege([privileges.GOAL_CONFIG_ACCESS, privileges.GOAL_CONFIG_EDIT]))
      if (current()) settings.value = result
      return result
    } catch (caught) {
      if (current()) settingsError.value = caught
      console.error('Error fetching Goal settings:', caught)
      throw caught
    } finally {
      if (current()) settingsLoading.value = false
    }
  }

  async function updateSettings(data: GoalSettingsUpdate): Promise<GoalSettings> {
    const generation = refreshGeneration, session = sessionGeneration()
    const current = () => generation === refreshGeneration && session === sessionGeneration()
    settingsSaving.value = true
    try {
      const result = await goalService.updateSettings(data)
      if (current()) settings.value = result
      return result
    } catch (caught) {
      console.error('Error updating Goal settings:', caught)
      throw caught
    } finally {
      if (current()) settingsSaving.value = false
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
        categoryId: categoryFilter.value,
        sortBy: sortBy.value,
        descending: sortDescending.value,
      })
      if (!current()) return
      if (!result.items.length && page.value > 0) {
        page.value = Math.min(page.value - 1, Math.max(0, Math.ceil(result.total / pageSize.value) - 1))
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
    treeError.value = null
    try {
      const result = await goalService.tree()
      if (current()) treeGoals.value = result.items
    } catch (caught) {
      if (!current()) return
      treeError.value = caught
      throw caught
    }
  }

  async function fetchCycles(id: string, targetPage?: number): Promise<void> {
    const current = beginRequest('cycles')
    if (targetPage !== undefined) cyclePage.value = targetPage
    cyclesLoading.value = true
    cyclesError.value = null
    try {
      const result = await goalService.listCycles(id, {
        page: cyclePage.value,
        pageSize: cyclePageSize.value,
      })
      if (!current()) return
      if (!result.items.length && cyclePage.value > 1) {
        cyclePage.value = Math.min(cyclePage.value - 1, Math.max(1, Math.ceil(result.total / cyclePageSize.value)))
        await fetchCycles(id, cyclePage.value)
        return
      }
      cycles.value = result.items
      cycleTotal.value = result.total
      cyclePage.value = result.page
      cyclePageSize.value = result.page_size
    } catch (caught) {
      if (!current()) return
      cyclesError.value = caught
      throw caught
    } finally {
      if (current()) cyclesLoading.value = false
    }
  }

  async function fetchGoal(id: string, targetCyclePage?: number): Promise<GoalDetail | null> {
    const current = beginRequest('detail')
    requests.cycles++
    cyclesLoading.value = false
    detailLoading.value = true
    detailError.value = null
    if (currentGoal.value?.id !== id) {
      currentGoal.value = null
      cycles.value = []
      cycleTotal.value = 0
      cyclePage.value = 1
    }
    try {
      const previousGoal = currentGoal.value
      const fetchedGoal = await goalService.get(id)
      if (!current()) return null
      currentGoal.value = previousGoal?.id === id
        ? mergeGoalSnapshot(previousGoal, fetchedGoal)
        : fetchedGoal
      if (cyclesActive.value) await fetchCycles(
        id, targetCyclePage ?? (previousGoal?.id === id ? cyclePage.value : 1),
      ).catch(() => undefined)
      return current() ? currentGoal.value : null
    } catch (caught) {
      if (!current()) return null
      detailError.value = caught
      throw caught
    } finally {
      if (current()) detailLoading.value = false
    }
  }

  async function setCyclesActive(active: boolean): Promise<void> {
    cyclesActive.value = active
    if (active && currentGoal.value) await fetchCycles(currentGoal.value.id)
    if (!active) {
      requests.cycles++
      cyclesLoading.value = false
    }
  }

  function replaceGoal(goal: Goal): boolean {
    const known = currentGoal.value?.id === goal.id ? currentGoal.value
      : goals.value.find(item => item.id === goal.id)
    if (known && goal.revision < known.revision) return false
    const index = goals.value.findIndex(item => item.id === goal.id)
    if (index >= 0) mergeGoalSnapshot(goals.value[index], goal)
    if (currentGoal.value?.id === goal.id) {
      mergeGoalSnapshot(currentGoal.value, goal)
    }
    const node = treeGoals.value.find(item => item.id === goal.id)
    const structureChanged = !node || node.parent_goal_id !== goal.parent_goal_id
      || node.agent_id !== goal.agent_id || node.title !== goal.title
    if (node) {
      for (const key of ['title', 'agent_id', 'agent_name', 'agent_code', 'status',
        'parent_goal_id', 'next_cycle_at', 'cycle_delay_seconds', 'children_count'] as const) {
        Object.assign(node, { [key]: goal[key] })
      }
    }
    return structureChanged
  }

  async function createGoal(data: GoalCreate): Promise<Goal> {
    const generation = refreshGeneration, session = sessionGeneration()
    const goal = await goalService.create(data)
    if (generation !== refreshGeneration || session !== sessionGeneration()) return goal
    await Promise.all([fetchGoals(0), fetchTree()])
    return goal
  }

  async function updateGoal(id: string, data: GoalUpdate): Promise<Goal> {
    const generation = refreshGeneration, session = sessionGeneration()
    const goal = await goalService.update(id, data)
    if (generation !== refreshGeneration || session !== sessionGeneration()) return goal
    const tree = replaceGoal(goal)
    scheduleRefresh({ list: true, tree, cycles: currentGoal.value?.id === id })
    return goal
  }

  async function command(
    action: 'pause' | 'resume' | 'complete' | 'runNow',
    goal: Goal,
  ): Promise<Goal> {
    const generation = refreshGeneration, session = sessionGeneration()
    const updated = await goalService[action](goal.id, { expected_revision: goal.revision })
    if (generation !== refreshGeneration || session !== sessionGeneration()) return updated
    const tree = replaceGoal(updated)
    scheduleRefresh({ list: true, tree, cycles: currentGoal.value?.id === goal.id })
    return updated
  }

  async function deleteGoal(id: string): Promise<void> {
    const generation = refreshGeneration, session = sessionGeneration()
    await goalService.delete(id)
    if (generation !== refreshGeneration || session !== sessionGeneration()) return
    goals.value = goals.value.filter(goal => goal.id !== id)
    if (currentGoal.value?.id === id) {
      clearSelection()
    }
    scheduleRefresh()
  }

  function scheduleRefresh(changes: Partial<Refresh> = { list: true, tree: true }): void {
    for (const key of Object.keys(changes) as (keyof Refresh)[]) {
      pendingRefresh[key] ||= Boolean(changes[key])
    }
    if (refreshTimer || refreshRunning) return
    const generation = refreshGeneration
    refreshTimer = setTimeout(() => {
      refreshTimer = null
      refreshRunning = true
      const refresh = pendingRefresh
      pendingRefresh = { list: false, tree: false, detail: false, cycles: false }
      const selectedId = currentGoal.value?.id
      // Settled reads retain each view's error and keep one failed endpoint from
      // preventing updates elsewhere. Events arriving in flight form one next batch.
      void Promise.allSettled([
        ...(refresh.list && listActive.value ? [fetchGoals()] : []),
        ...(refresh.tree ? [fetchTree()] : []),
        ...(refresh.detail && selectedId ? [fetchGoal(selectedId)] : []),
        ...(refresh.cycles && !refresh.detail && cyclesActive.value && selectedId
          ? [fetchCycles(selectedId)] : []),
      ]).finally(() => {
        if (generation !== refreshGeneration) return
        refreshRunning = false
        if (Object.values(pendingRefresh).some(Boolean)) scheduleRefresh({})
      })
    }, 300)
  }

  function onGoalCreate(): void {
    scheduleRefresh()
  }

  function onGoalUpdate(response: { data: Goal }): void {
    const tree = replaceGoal(response.data)
    scheduleRefresh({ list: true, tree, cycles: currentGoal.value?.id === response.data.id,
      detail: currentGoal.value?.parent_goal_id === response.data.id })
  }

  function onGoalDelete(response: { data: { id: string } }): void {
    goals.value = goals.value.filter(goal => goal.id !== response.data.id)
    if (currentGoal.value?.id === response.data.id) {
      clearSelection()
    }
    scheduleRefresh()
  }

  function onTaskUpdate(response: { data: { goal_id?: string | null } }): void {
    const id = response.data.goal_id
    if (id) scheduleRefresh({ list: true, detail: currentGoal.value?.id === id })
  }

  function onRuntimeUpdate(response: { data: Omit<GoalSettings, 'schedule'> }): void {
    settings.value = { ...response.data, schedule: settings.value?.schedule ?? [] }
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
    websocket.onEvent('goal_runtime', 'update', onRuntimeUpdate)
    isSubscribed.value = true
  }

  function unsubscribe(): void {
    refreshGeneration++
    refreshRunning = false
    pendingRefresh = { list: false, tree: false, detail: false, cycles: false }
    requests.settings++
    requests.list++
    requests.tree++
    clearSelection()
    loading.value = false
    settingsLoading.value = false
    settingsSaving.value = false
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
    websocket.offEvent('goal_runtime', 'update', onRuntimeUpdate)
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
    cyclesActive,
    listActive,
    setCyclesActive,
    detailError,
    cyclesError,
    treeError,
    settingsError,
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
    categoryFilter,
    sortBy,
    sortDescending,
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
}

export const useGoalStore = defineStore('goal', createGoalState)
