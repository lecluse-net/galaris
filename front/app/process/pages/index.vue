<template>
  <q-page class="process-page q-pa-md">
    <PageHeader help-key="processes" :help-text="$t('contextHelpPages.processes')" :icon="navigationIcon('account_tree')" :title="t('nav.processes')" :description="t('nav.processes_desc')" />

    <div class="process-toolbar q-mb-md">
      <q-input v-model="definitionFilter" class="process-definition-filter" dense outlined clearable debounce="250" :placeholder="t('processes.filter')">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <AgentSelect
        v-model="definitionAgentFilter"
        :options="definitionAgentOptions"
        :label="t('processes.externalAgentFilter')"
        clearable
        dense
        outlined
        class="process-agent-filter"
      />
      <div class="process-toolbar-actions">
        <q-btn outline icon="refresh" :label="t('processes.refresh')" @click="refreshCatalogue" />
        <q-btn v-if="canAdmin" color="secondary" icon="sync" :label="t('processes.syncN8n')" :loading="syncingN8n" @click="syncN8n" />
      </div>
    </div>
    <div v-if="(isDev && canEdit) || canAdmin" class="process-add-actions q-mb-md">
      <q-btn v-if="isDev && canEdit" color="primary" icon="add" :label="t('nativeProcesses.newProcess')" to="/process/new-internal" />
      <q-btn v-if="canAdmin" color="primary" icon="add" :label="t('processes.importExternal')" to="/process/new-external" />
    </div>

    <q-banner v-if="n8nConnectionError" role="alert" rounded class="n8n-error-banner q-mb-md">
      <template #avatar><q-icon name="error" color="negative" /></template>
      {{ store.health?.message }}
      <template #action>
        <q-icon name="refresh" color="primary" size="20px" class="cursor-pointer" role="button" tabindex="0" :aria-label="t('processes.refresh')"
          @click="loadOperations" @keydown.enter.prevent="loadOperations" @keydown.space.prevent="loadOperations" />
      </template>
    </q-banner>

    <q-banner v-if="store.error" role="alert" class="q-mb-md">
      {{ t('processes.genericError') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="refreshCatalogue" /></template>
    </q-banner>
    <ProcessCatalogue
      ref="catalogue"
      :definitions="store.definitions" :tools="processTools" :agents="store.agents"
      :filter="definitionFilter" :external-loading="store.loading" :runs-revision="runListRevision"
      @open-run="openRun"
    />

    <q-dialog v-model="n8nDialog">
      <q-card class="n8n-dialog galaris-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <q-icon name="sync" size="sm" />
          <div class="text-subtitle1 q-ml-sm">{{ t('processes.syncN8n') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('processes.close')" />
        </q-card-section>
        <q-card-section class="galaris-dialog-body">
          <div v-if="syncingN8n || healthLoading" class="flex flex-center q-pa-md"><q-spinner color="primary" size="2em" /></div>
          <q-banner v-if="syncError || healthError" role="alert" class="n8n-error-banner q-mb-sm">{{ syncError || healthError }}</q-banner>
          <q-banner v-if="store.health && !syncingN8n && !healthLoading">
            <template #avatar><q-icon :name="healthIcon" :color="store.health.status === 'healthy' ? 'positive' : 'negative'" /></template>
            <div>{{ store.health.message }}</div>
            <div v-if="store.operations" class="text-caption q-mt-sm">
              {{ t('processes.pendingJobs', { count: store.operations.pending_start_jobs }) }} ·
              {{ t('processes.staleRuns', { count: store.operations.stale_active_runs }) }} ·
              {{ t('processes.failedToday', { count: store.operations.failed_last_24h }) }}
            </div>
          </q-banner>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-if="canAdmin" color="secondary" icon="sync" :label="t('processes.syncN8n')" :loading="syncingN8n" @click="syncN8n" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <ExternalRunDialog v-if="selectedRunId" :run-id="selectedRunId" @close="selectedRunId = null; runListRevision++" />
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { AgentSelect } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader, defineAsyncView } from '@/core/util'
import ProcessCatalogue from '../components/ProcessCatalogue.vue'
import { useProcessStore } from '../stores/processStore'
import { processService, type ProcessTool } from '../services/processService'

const ExternalRunDialog = defineAsyncView(() => import('../components/ExternalRunDialog.vue'))

const isDev = import.meta.env.VITE_APP_ENV === 'dev'
const store = useProcessStore()
const $q = useQuasar()
const { t } = useI18n()
const privilegeStore = usePrivilegeStore()
const canAdmin = computed(() => privilegeStore.hasPrivilege(privileges.PROCESS_ADMIN))
const canEdit = computed(() => canAdmin.value || privilegeStore.hasPrivilege(privileges.PROCESS_EDIT))
const catalogue = useTemplateRef('catalogue')
const runListRevision = ref(0)
const selectedRunId = ref<string | null>(null)
function openRun(run: { id: string }): void { selectedRunId.value = run.id }
const definitionFilter = ref('')
const definitionAgentFilter = ref<number | null>(null)
const processTools = ref<ProcessTool[]>([])
const agentOptions = computed(() => store.agents.map(agent => ({ label: agent.label, value: agent.id })))
const definitionAgentOptions = computed(() => [
  { label: t('processes.allAgents'), value: null },
  ...agentOptions.value,
])

const n8nDialog = ref(false), syncingN8n = ref(false), healthLoading = ref(false)
const syncError = ref(''), healthError = ref('')
let healthRequest = 0, disposed = false
const n8nConnectionError = computed(() => store.health?.tool_code === 'n8n' && store.health.status === 'error' && !(store.health.details ?? []).includes('not_configured'))
async function syncN8n(): Promise<void> {
  if (!canAdmin.value) return
  n8nDialog.value = true
  if (syncingN8n.value) return
  syncingN8n.value = true; syncError.value = ''
  // A startup health response cannot overwrite this synchronization's diagnostic.
  healthRequest++
  try {
    const discovered = await processService.syncDefinitions('n8n')
    if (disposed) return
    store.discovered = discovered
    await refreshCatalogue()
  } catch (error) { if (!disposed) syncError.value = errorDetail(error) }
  finally {
    if (!disposed) { await loadOperations(); syncingN8n.value = false }
  }
}
function errorDetail(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
  return t('processes.genericError')
}
const healthIcon = computed(() => ({ healthy: 'check_circle', degraded: 'warning', error: 'error' } as const)[store.health?.status ?? 'error'])
function notify(type: 'positive' | 'negative', message: string): void { $q.notify({ type, message }) }
async function loadOperations(): Promise<void> {
  const request = ++healthRequest
  healthLoading.value = true; healthError.value = ''
  const [health, operations] = await Promise.allSettled([processService.toolHealth('n8n'), processService.operations()])
  if (disposed || request !== healthRequest) return
  if (health.status === 'fulfilled') store.health = health.value
  else healthError.value = errorDetail(health.reason)
  if (operations.status === 'fulfilled') store.operations = operations.value
  healthLoading.value = false
}
onBeforeUnmount(() => { disposed = true; healthRequest++ })


async function refreshCatalogue(): Promise<void> {
  runListRevision.value++
  await Promise.all([
    catalogue.value?.reload(),
    store.loadDefinitions(definitionAgentFilter.value ?? undefined).catch((error: unknown) => { notify('negative', errorDetail(error)) }),
  ])
}

watch(definitionAgentFilter, agentId => {
  void store.loadDefinitions(agentId ?? undefined).catch((error: unknown) => { console.error(error) })
})

onMounted(async () => {
  try {
    await Promise.all([
      processService.tools().then(tools => {
        processTools.value = tools
      }),
      store.loadAll(), loadOperations(),
    ])
  } catch { notify('negative', t('processes.genericError')) }
})
</script>

<style scoped>
.n8n-dialog { width: 650px; max-width: 96vw; }
.n8n-error-banner { background: var(--solaire-red-light); }
body.body--dark .n8n-error-banner { background: var(--solaire-red-dark); }
.process-toolbar { display: flex; align-items: center; gap: 8px; }
.process-definition-filter { flex: 1 1 auto; min-width: 0; }
.process-agent-filter { flex: 0 1 260px; min-width: 200px; }
.process-toolbar-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.process-add-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.min-width-0 { min-width: 0; }
@media (max-width: 1023px) {
  .process-toolbar { align-items: stretch; flex-wrap: wrap; }
  .process-definition-filter { flex-basis: 100%; }
  .process-agent-filter { flex: 1 1 260px; }
  .process-toolbar-actions { width: 100%; }
}
@media (max-width: 599px) {
  .process-page { padding: 8px; }
  .process-toolbar-actions { display: grid; grid-template-columns: 1fr; }
  .process-agent-filter { flex-basis: 100%; width: 100%; }
  .process-toolbar-actions .q-btn { width: 100%; }
}
</style>
