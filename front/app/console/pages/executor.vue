<template>
  <q-page class="q-pa-md">
    <PageHeader :icon="navigationIcon('terminal')" :title="t('nav.executor')" :description="t('nav.executor_desc')">
      <template #actions>
        <q-btn color="primary" icon="refresh" :label="t('console.refresh')" :loading="store.loading" @click="store.refresh" />
      </template>
    </PageHeader>

    <q-banner v-if="store.error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error" /></template>
      {{ t('console.unavailable') }} — {{ store.error }}
    </q-banner>

    <template v-if="store.status">
      <div class="row q-col-gutter-md q-mb-md">
        <div v-for="card in statusCards" :key="card.label" class="col-12 col-sm-6 col-lg-3">
          <q-card flat bordered><q-card-section class="row items-center no-wrap">
            <q-avatar :color="card.color" text-color="white" :icon="card.icon" />
            <div class="q-ml-md"><div class="text-caption text-grey-7">{{ card.label }}</div><div class="text-h6">{{ card.value }}</div></div>
          </q-card-section></q-card>
        </div>
      </div>

      <q-card flat bordered class="q-mb-md">
        <q-card-section class="text-subtitle1 text-weight-medium">{{ t('console.users') }}</q-card-section>
        <q-separator />
        <q-table flat :rows="store.status.users" :columns="userColumns" row-key="agent_id" :no-data-label="t('console.noUsers')">
          <template #body-cell-state="props"><q-td :props="props"><q-chip dense :color="props.row.enabled ? 'positive' : 'grey'" text-color="white">{{ t(props.row.enabled ? 'console.enabled' : 'console.disabled') }}</q-chip></q-td></template>
          <template #body-cell-usage="props"><q-td :props="props">{{ formatBytes(props.row.usage_bytes) }}</q-td></template>
          <template #body-cell-actions="props"><q-td :props="props" class="q-gutter-xs">
            <template v-if="canAdmin">
              <q-btn flat dense round :color="props.row.enabled ? 'negative' : 'positive'" :icon="props.row.enabled ? 'person_off' : 'person'" :title="t(props.row.enabled ? 'console.disable' : 'console.enable')" @click="toggleUser(props.row)" />
              <q-btn flat dense round icon="key" :title="t('console.rotateKey')" @click="rotateUserKey(props.row)" />
              <q-btn flat dense round icon="cleaning_services" :title="t('console.clearCache')" @click="runAction('cleanup_caches', { agent_id: props.row.agent_id })" />
            </template>
          </q-td></template>
        </q-table>
      </q-card>

      <q-card flat bordered class="q-mb-md">
        <q-card-section class="text-subtitle1 text-weight-medium">{{ t('console.sessions') }}</q-card-section>
        <q-separator />
        <q-table flat :rows="store.status.sessions" :columns="sessionColumns" row-key="run_id" :no-data-label="t('console.noSessions')">
          <template #body-cell-running="props"><q-td :props="props"><q-chip dense :color="props.row.running ? 'positive' : 'grey'" text-color="white">{{ t(props.row.running ? 'console.running' : 'console.finished') }}</q-chip></q-td></template>
          <template #body-cell-started="props"><q-td :props="props">{{ formatDate(props.row.started_at) }}</q-td></template>
          <template #body-cell-actions="props"><q-td :props="props"><q-btn v-if="canAdmin && props.row.running" flat dense round color="negative" icon="stop" :title="t('console.stop')" @click="stopSession(props.row.run_id)" /></q-td></template>
        </q-table>
      </q-card>

      <q-card v-if="canAdmin" flat bordered>
        <q-card-section>
          <div class="text-subtitle1 text-weight-medium q-mb-md">{{ t('console.maintenance') }}</div>
          <div class="row q-gutter-sm">
            <q-btn outline icon="cleaning_services" :label="t('console.cleanPartials')" :loading="store.actionLoading" @click="runAction('cleanup_partials')" />
            <q-btn outline color="warning" icon="restart_alt" :label="t('console.recycle')" :loading="store.actionLoading" @click="recycle" />
          </div>
        </q-card-section>
      </q-card>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTableColumn } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader, formatFileSize } from '@/core/util'
import { useConsoleStore } from '../stores/consoleStore'
import type { ExecutorUser } from '../services/consoleService'

const { t, locale } = useI18n()
const $q = useQuasar()
const store = useConsoleStore()
const privilegeStore = usePrivilegeStore()
const canAdmin = computed(() => privilegeStore.hasPrivilege(privileges.CONSOLE_ADMIN))
const statusCards = computed(() => store.status ? [
  { label: t('console.version'), value: store.status.version, icon: 'deployed_code', color: 'primary' },
  { label: t('console.ssh'), value: store.status.ssh, icon: 'key', color: store.status.ssh === 'running' ? 'positive' : 'warning' },
  { label: t('console.disk'), value: `${formatBytes(store.status.disk.used)} / ${formatBytes(store.status.disk.total)}`, icon: 'hard_drive', color: 'secondary' },
  { label: t('console.memory'), value: `${formatBytes(store.status.resources.memory_current ?? 0)} / ${store.status.resources.memory_limit === null ? '∞' : formatBytes(store.status.resources.memory_limit)}`, icon: 'memory', color: 'teal' },
  { label: t('console.processes'), value: `${store.status.resources.pids_current} / ${store.status.resources.pids_limit ?? '∞'}`, icon: 'account_tree', color: 'indigo' },
  { label: t('console.load'), value: store.status.load_average.map(value => value.toFixed(2)).join(' · '), icon: 'speed', color: 'orange' },
  { label: t('console.sessions'), value: String(store.status.active_sessions), icon: 'terminal', color: 'purple' },
] : [])

const userColumns = computed<QTableColumn[]>(() => [
  { name: 'code', label: t('console.code'), field: 'code', align: 'left', sortable: true },
  { name: 'uid', label: t('console.uid'), field: 'uid', align: 'left', sortable: true },
  { name: 'state', label: t('console.state'), field: 'enabled', align: 'left' },
  { name: 'usage', label: t('console.usage'), field: 'usage_bytes', align: 'left', sortable: true },
  { name: 'home', label: t('console.home'), field: 'home', align: 'left' },
  { name: 'actions', label: t('console.actions'), field: 'actions', align: 'right' },
])
const sessionColumns = computed<QTableColumn[]>(() => [
  { name: 'code', label: t('console.code'), field: 'code', align: 'left', sortable: true },
  { name: 'command', label: t('console.command'), field: 'command', align: 'left' },
  { name: 'cwd', label: t('console.cwd'), field: 'cwd', align: 'left' },
  { name: 'running', label: t('console.state'), field: 'running', align: 'left' },
  { name: 'started', label: t('console.started'), field: 'started_at', align: 'left' },
  { name: 'actions', label: t('console.actions'), field: 'actions', align: 'right' },
])

function formatBytes(value: number): string {
  return formatFileSize(value, locale.value)
}
function formatDate(value?: number): string { return value ? new Date(value * 1000).toLocaleString() : '—' }
function confirm(message: string): Promise<boolean> { return new Promise(resolve => showConfirmationDialog({ message, cancel: true }).onOk(() => resolve(true)).onCancel(() => resolve(false))) }
async function notifyAction(operation: string, payload: Record<string, unknown> = {}): Promise<void> {
  try { await store.action(operation, payload); $q.notify({ type: 'positive', message: t('console.success') }) }
  catch (error) { $q.notify({ type: 'negative', message: `${t('console.error')}: ${String(error)}` }) }
}
async function runAction(operation: string, payload: Record<string, unknown> = {}): Promise<void> { await notifyAction(operation, payload) }
async function toggleUser(user: ExecutorUser): Promise<void> {
  if (user.enabled && !await confirm(t('console.confirmDisable', { code: user.code }))) return
  await notifyAction(user.enabled ? 'disable_user' : 'enable_user', { agent_id: user.agent_id })
}
async function rotateUserKey(user: ExecutorUser): Promise<void> {
  if (!await confirm(t('console.confirmRotate', { code: user.code }))) return
  try { const result = await store.provision(user.agent_id); $q.notify({ type: 'positive', message: t('console.provisioned', { code: result.agent_code }) }) }
  catch (error) { $q.notify({ type: 'negative', message: `${t('console.error')}: ${String(error)}` }) }
}
async function stopSession(runId: string): Promise<void> { if (await confirm(t('console.confirmStop'))) await notifyAction('stop_session', { run_id: runId }) }
async function recycle(): Promise<void> { if (await confirm(t('console.confirmRecycle'))) await notifyAction('recycle') }

onMounted(store.refresh)
</script>
