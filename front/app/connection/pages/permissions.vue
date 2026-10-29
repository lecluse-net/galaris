<route lang="json">
{ "path": "/permissions" }
</route>

<template>
  <q-page class="q-pa-md">
    <PageHeader icon="verified_user" :title="t('permissions.title')" :description="t('permissions.dashboard.description')" />
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-4">
        <q-select v-model="agentId" :options="filteredAgents" option-label="label" option-value="id" emit-value map-options
          use-input fill-input hide-selected outlined dense :label="t('permissions.agent')" :loading="initializing" @filter="filterAgents" />
      </div>
      <div class="col-12 col-md">
        <q-input v-model="search" clearable outlined dense :label="t('permissions.dashboard.search')" :disable="agentId === null">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div class="col-auto">
        <q-btn outline color="primary" icon="refresh" :label="t('permissions.refresh')" :loading="initializing" @click="refresh" />
      </div>
      <div class="col-auto">
        <q-btn outline color="primary" icon="filter_alt_off" :label="t('permissions.dashboard.resetFilters')"
          :disable="agentId === null" @click="resetFilters" />
      </div>
    </div>
    <q-banner v-if="initializeError" role="alert" class="q-mb-md">{{ t('permissions.error') }}
      <template #action><q-btn outline color="primary" :label="t('permissions.retry')" @click="initialize" /></template>
    </q-banner>
    <q-banner v-else-if="!initializing && agentId === null" class="q-mb-md">{{ t('permissions.dashboard.selectAgent') }}</q-banner>
    <template v-if="agentId !== null && dashboard">
      <div class="row q-col-gutter-sm q-mb-md" role="group" :aria-label="t('permissions.dashboard.loadedResults')">
        <div v-for="item in summary" :key="item.state" class="col-6 col-md">
          <q-card flat bordered class="permission-summary full-height" role="button" tabindex="0"
            :class="{ 'permission-summary-active': state === item.state }" :style="{ '--permission-filter-accent': solaireCss[item.color].accent }"
            :aria-pressed="state === item.state" :aria-label="t(`permissions.dashboard.states.${item.state}`)"
            @click="toggleState(item.state)" @keydown.enter.prevent="toggleState(item.state)" @keydown.space.prevent="toggleState(item.state)">
            <q-card-section class="row items-center q-gutter-sm">
              <q-icon :name="item.icon" :style="{ color: solaireCss[item.color].accent }" size="sm" />
              <div><div class="text-h5">{{ item.count }}</div><div>{{ t(`permissions.dashboard.states.${item.state}`) }}</div></div>
            </q-card-section>
          </q-card>
        </div>
        <div class="col-6 col-md">
          <q-card flat bordered class="permission-summary full-height" role="button" tabindex="0"
            :class="{ 'permission-summary-active': customizedOnly }" :style="{ '--permission-filter-accent': solaireCss.blue.accent }"
            :aria-pressed="customizedOnly" :aria-label="t('permissions.dashboard.customizedOnly')"
            @click="customizedOnly = !customizedOnly" @keydown.enter.prevent="customizedOnly = !customizedOnly" @keydown.space.prevent="customizedOnly = !customizedOnly">
            <q-card-section class="row items-center no-wrap q-gutter-sm full-height">
              <q-icon name="tune" :style="{ color: solaireCss.blue.accent }" size="sm" />
              <div class="col"><div class="text-h5">{{ customizedCount }}</div><div>{{ t('permissions.dashboard.customizedOnly') }}</div></div>
            </q-card-section>
            <q-tooltip>{{ t('permissions.dashboard.customizedHint') }}</q-tooltip>
          </q-card>
        </div>
      </div>
      <p class="text-caption">{{ t('permissions.dashboard.scopeNote') }}</p>
      <PermissionDashboardPanel v-for="panel in dashboard.panels" :key="`${agentId}:${panel.id}`" :definition="panel"
        :agent-id="agentId" :search="appliedSearch" :state="state" :revision="revision" :customized-only="customizedOnly"
        @counts="counts[panel.id] = $event" @customized-count="customizedCounts[panel.id] = $event" @changed="refresh" />
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, onWatcherCleanup, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PageHeader, solaireCss } from '@/core/util'
import { permissionStates } from '../permissionPresentation'
import { AUTH_TOKEN_CHANGED_EVENT, getStoredAccessToken, sessionGeneration } from '@/core/api'
import { getAgentSelection, type AgentSelectionOption } from '@/app/agent'
import PermissionDashboardPanel from '../components/PermissionDashboardPanel.vue'
import { createPermissionDashboard } from '../services/permissionDashboardSources'
import type { PermissionCounts, PermissionState } from '../services/permissionDashboard'
import { getActionAuthorization } from '../services/permissionService'
const { t } = useI18n()
const route = useRoute(), router = useRouter()
const agents = ref<AgentSelectionOption[]>([]), filteredAgents = ref<AgentSelectionOption[]>([])
const agentId = ref<number | null>(null), search = ref<string | null>(''), state = ref<PermissionState>('all')
const customizedOnly = ref(false), appliedSearch = ref('')
const initializing = ref(false), initializeError = ref(false), revision = ref(0)
const counts = ref<Record<string, PermissionCounts>>({})
const customizedCounts = ref<Record<string, number>>({})
const customizedCount = computed(() => Object.values(customizedCounts.value).reduce((sum, count) => sum + count, 0))
const dashboard = shallowRef<ReturnType<typeof createPermissionDashboard>>()
const states = ['all', 'allowed', 'denied', 'ask', 'pending'] as const
const summary = computed(() => states.filter(value => value !== 'all').map(state => ({
  state, ...permissionStates[state], count: Object.values(counts.value).reduce((sum, current) => sum + (current[state] ?? 0), 0),
})))
let disposed = false, active = true, generation = 0
let requestAgentId: number | undefined
let session = sessionGeneration()
function sessionChanged() {
  const next = sessionGeneration()
  if (next === session) return
  session = next; generation++; dashboard.value?.dispose(); dashboard.value = undefined
  agents.value = []; filteredAgents.value = []; agentId.value = null; counts.value = {}; customizedCounts.value = {}; requestAgentId = undefined
  if (getStoredAccessToken()) void initialize()
}
function filterAgents(value: string, update: (callback: () => void) => void) {
  update(() => { filteredAgents.value = agents.value.filter(agent => agent.label.toLocaleLowerCase().includes(value.toLocaleLowerCase())) })
}
function toggleState(value: Exclude<PermissionState, 'all'>) {
  state.value = state.value === value ? 'all' : value
}
function resetFilters() {
  search.value = ''; appliedSearch.value = ''; state.value = 'all'; customizedOnly.value = false
}
function refresh() {
  dashboard.value?.invalidate(); counts.value = {}; customizedCounts.value = {}; revision.value++
}
async function initialize() {
  const current = ++generation
  initializing.value = true; initializeError.value = false
  try {
    const selection = await getAgentSelection('management')
    const requestId = typeof route.query.request === 'string' ? route.query.request : undefined
    const request = requestId ? await getActionAuthorization(requestId) : undefined
    if (disposed || current !== generation) return
    const requested = request?.agent_id ?? Number(route.query.agent_id)
    const target = requested > 0 ? requested : agentId.value ?? selection[0]?.id ?? null
    if (target !== null && !selection.some(agent => agent.id === target)) throw new Error('Agent outside management scope')
    // Quasar closes dialogs on navigation. Canonicalize the deep link before
    // mounting its review, so adding agent_id cannot close an opening dialog.
    if (target !== null && (route.path !== '/permissions' || route.query.agent_id !== String(target))) {
      await router.replace({ path: '/permissions', query: { ...route.query, agent_id: String(target) } })
      if (disposed || current !== generation) return
    }
    agents.value = selection; filteredAgents.value = selection
    dashboard.value?.dispose()
    dashboard.value = createPermissionDashboard(t, selection)
    requestAgentId = request?.agent_id
    agentId.value = target
    counts.value = {}; customizedCounts.value = {}
  } catch { if (!disposed && current === generation) { initializeError.value = true; agentId.value = null } }
  finally { if (!disposed && current === generation) initializing.value = false }
}
watch(agentId, value => {
  refresh()
  if (value !== null && (route.query.agent_id !== String(value) || (route.query.request && requestAgentId !== value))) void router.replace({ path: '/permissions', query: { ...route.query, agent_id: String(value),
    ...(requestAgentId !== value ? { request: undefined } : {}) } })
})
watch(search, value => {
  if (!value) { appliedSearch.value = ''; return }
  const timeout = setTimeout(() => { appliedSearch.value = value }, 250)
  onWatcherCleanup(() => clearTimeout(timeout))
})
watch(() => [appliedSearch.value, state.value, customizedOnly.value], () => { counts.value = {}; customizedCounts.value = {} })
watch(() => route.query.agent_id, value => {
  if (initializing.value) return
  const target = Number(value)
  if (target > 0 && target !== agentId.value && agents.value.some(agent => agent.id === target)) agentId.value = target
})
watch(() => route.query.request, value => { if (!initializing.value && typeof value === 'string') void initialize() })
onMounted(() => { window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged); window.addEventListener('storage', sessionChanged); void initialize() })
onDeactivated(() => { active = false; dashboard.value?.dispose() })
onActivated(() => { if (!active) { active = true; refresh() } })
onBeforeUnmount(() => { disposed = true; generation++; dashboard.value?.dispose(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged); window.removeEventListener('storage', sessionChanged) })
</script>

<style scoped>
.permission-summary { cursor: pointer; transition: border-color 160ms ease, box-shadow 160ms ease; }
.permission-summary:hover, .permission-summary-active { border-color: var(--permission-filter-accent); }
.permission-summary-active { box-shadow: 0 0 0 1px var(--permission-filter-accent); }
.permission-summary:focus-visible { outline: 2px solid var(--permission-filter-accent); outline-offset: 2px; }
</style>
