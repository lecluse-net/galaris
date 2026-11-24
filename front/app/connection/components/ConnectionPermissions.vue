<template>
  <div>
    <q-card v-if="servicePermission?.description" flat bordered class="q-mb-md">
      <q-card-section>
        <h3 class="text-subtitle2 q-mt-none q-mb-xs">{{ t('connection.permissionScope') }}</h3>
        <div class="permission-parameters">{{ servicePermission.description }}</div>
      </q-card-section>
    </q-card>
    <div class="row items-center q-gutter-sm q-mb-md">
      <q-input v-model="search" class="col" outlined dense clearable :label="t('connection.auth.search')">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-btn flat round color="primary" icon="refresh" :aria-label="t('permissions.refresh')" :loading="loading" @click="refresh" />
    </div>
    <q-banner v-if="error || actionError" role="alert" class="q-mb-md">{{ t('permissions.error') }}
      <template #action><q-btn outline color="primary" :label="t('permissions.retry')" @click="refresh" /></template>
    </q-banner>
    <q-banner v-for="warning in warnings" :key="warning" role="status" class="q-mb-md">{{ warning }}</q-banner>
    <PermissionEntryTable :entries="entries" nested policy-scopes :loading="loading" :busy="busy" @change="save" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { createPermissionDashboard } from '../services/permissionDashboardSources'
import { waitForFunctionPolicyWrites } from '../services/connectionService'
import type { Connection } from '../services/connectionService'
import { filterPermissionEntries, type PermissionControl, type PermissionEntry } from '../services/permissionDashboard'
import PermissionEntryTable from './PermissionEntryTable.vue'

const props = defineProps<{ connection: Connection }>()
const { t } = useI18n()
const search = ref(''), warnings = ref<string[]>([])
const servicePermission = ref<PermissionEntry>()
const entries = computed(() => {
  const functions = servicePermission.value?.children ?? []
  return filterPermissionEntries(functions, { search: search.value ?? '', state: 'all', offset: 0, limit: functions.length }).items
})
const loading = ref(false), busy = ref(false), error = ref(false)
const actionError = ref(false)
let generation = 0, disposed = false
let dashboard = createPermissionDashboard(t, [], props.connection.id)
let controller: AbortController | undefined
async function load() {
  const current = ++generation
  controller?.abort()
  const request = controller = new AbortController()
  loading.value = true; error.value = false; servicePermission.value = undefined; warnings.value = []
  try {
    await waitForFunctionPolicyWrites(props.connection.service_id)
    if (current !== generation || disposed) return
    const panel = dashboard.panels.find(panel => panel.id === 'functions')!
    const page = await panel.load!({ agentId: props.connection.agent_id, search: '', state: 'all',
      offset: 0, limit: 500, signal: request.signal, toolId: props.connection.service_id })
    if (current !== generation || disposed) return
    servicePermission.value = page.items.find(row => row.toolId === props.connection.service_id)
    warnings.value = page.warnings ?? []
  } catch { if (current === generation && !disposed) error.value = true }
  finally { if (current === generation && !disposed) loading.value = false }
}
function refresh() { actionError.value = false; dashboard.invalidate(); void load() }
async function save(row: PermissionEntry, control: PermissionControl, value: string) {
  if (busy.value || loading.value || control.disabled || (control.value === value && !control.allowReselect)
    || !entries.value.includes(row) || !control.options.some(option => option.value === value && !option.disable)) return
  const connectionId = props.connection.id
  busy.value = true; actionError.value = false
  try { await control.save(value) }
  catch { if (!disposed && connectionId === props.connection.id) actionError.value = true }
  finally {
    if (!disposed) {
      busy.value = false
      if (connectionId === props.connection.id) { dashboard.invalidate(); void load() }
    }
  }
}
watch(() => [props.connection.id, props.connection.agent_id, props.connection.service_id], () => {
  actionError.value = false
  dashboard.dispose(); dashboard = createPermissionDashboard(t, [], props.connection.id); void load()
})
void load()
onBeforeUnmount(() => { disposed = true; generation++; controller?.abort(); dashboard.dispose() })
</script>

<style scoped>
.permission-parameters { overflow-wrap: anywhere; white-space: pre-wrap; }
</style>
