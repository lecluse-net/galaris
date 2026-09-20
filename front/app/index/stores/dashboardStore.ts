import { defineStore } from 'pinia'
import { nextTick, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { useAuthorizeStore, usePrivilegeStore, privileges } from '@/core/authorize'
import { useAuthStore } from '@/core/user'
import { dashboardService, type DashboardData } from '../services/dashboardService'

const CACHE_TTL_MS = 30_000
const CACHE_MONTHS = 6

function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export const useDashboardStore = defineStore('dashboard', () => {
  const auth = useAuthStore()
  const authorize = useAuthorizeStore()
  const access = usePrivilegeStore()
  const data = shallowRef<DashboardData | null>(null)
  const availableMonths = shallowRef<string[]>([])
  const selectedMonth = ref(currentMonth())
  const loading = ref(false)
  const error = ref<unknown>(null)
  const cache = new Map<string, { data: DashboardData; expires: number }>()
  const pending = new Map<string, Promise<DashboardData>>()
  let revision = 0
  let selection = 0
  let observedSession = sessionGeneration()
  let disposed = false

  function canRead(): boolean {
    return auth.isAuthenticated && (
      access.privileges.includes(privileges.TASK_ACCESS)
      || access.privileges.includes(privileges.TASK_EDIT)
    )
  }

  function reset(): void {
    revision++
    selection++
    cache.clear()
    pending.clear()
    data.value = null
    availableMonths.value = []
    error.value = null
    loading.value = false
    observedSession = sessionGeneration()
  }

  function scopeChanged(): void {
    const active = data.value !== null || loading.value
    reset()
    if (active) void nextTick(() => {
      if (!disposed && canRead()) void fetchDashboard()
    })
  }

  function sessionChanged(): void {
    if (observedSession !== sessionGeneration()) scopeChanged()
  }

  watch([
    () => auth.isAuthenticated,
    () => auth.user?.id,
    () => authorize.activeRole?.id,
    () => access.privileges,
  ], scopeChanged, { flush: 'sync' })
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
  window.addEventListener('storage', sessionChanged)
  onScopeDispose(() => {
    disposed = true
    reset()
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
    window.removeEventListener('storage', sessionChanged)
  })

  async function load(month: string, force: boolean): Promise<void> {
    sessionChanged()
    if (disposed || !canRead()) return
    const requestSelection = ++selection
    const requestRevision = revision
    const session = sessionGeneration()
    const currentScope = () => !disposed && revision === requestRevision && session === sessionGeneration()
    const current = () => currentScope() && requestSelection === selection
    selectedMonth.value = month
    error.value = null
    // A manual refresh also invalidates cached comparisons and available months.
    if (force) cache.clear()
    const cached = cache.get(month)
    if (cached && cached.expires > Date.now()) {
      cache.delete(month)
      cache.set(month, cached)
      data.value = cached.data
      loading.value = false
      return
    }
    cache.delete(month)
    if (data.value?.month !== month) data.value = null
    loading.value = true
    let response = pending.get(month)
    if (!response) {
      response = dashboardService.getDashboard(month)
      pending.set(month, response)
    }
    try {
      const result = await response
      if (!currentScope()) return
      availableMonths.value = result.available_months
      // Only the owner of this shared response inserts it into the cache.
      if (pending.get(month) === response) {
        cache.delete(month)
        cache.set(month, { data: result, expires: Date.now() + CACHE_TTL_MS })
        while (cache.size > CACHE_MONTHS) cache.delete(cache.keys().next().value!)
      }
      if (current()) data.value = result
    } catch (reason) {
      if (current()) error.value = reason
    } finally {
      if (currentScope() && pending.get(month) === response) pending.delete(month)
      if (current()) loading.value = false
    }
  }

  async function fetchDashboard(month = selectedMonth.value): Promise<void> {
    await load(month, true)
  }

  async function selectMonth(month: string): Promise<void> {
    await load(month, false)
  }

  return { data, availableMonths, selectedMonth, loading, error, fetchDashboard, selectMonth }
})
