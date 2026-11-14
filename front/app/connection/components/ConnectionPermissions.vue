<template>
  <div>
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
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { createPermissionDashboard } from '../services/permissionDashboardSources'
import { waitForFunctionPolicyWrites } from '../services/connectionService'
import type { Connection } from '../services/connectionService'
import type { PermissionControl, PermissionEntry } from '../services/permissionDashboard'
import PermissionEntryTable from './PermissionEntryTable.vue'

const props = defineProps<{ connection: Connection }>()
const { t } = useI18n()
const search = ref(''), entries = ref<PermissionEntry[]>([]), warnings = ref<string[]>([])
const loading = ref(false), busy = ref(false), error = ref(false)
const actionError = ref(false)
let generation = 0, disposed = false
let dashboard = createPermissionDashboard(t, [], props.connection.id)
let controller: AbortController | undefined
async function load() {
  const current = ++generation
  controller?.abort()
  const request = controller = new AbortController()
  loading.value = true; error.value = false; entries.value = []; warnings.value = []
  try {
    await waitForFunctionPolicyWrites(props.connection.tool_id)
    if (current !== generation || disposed) return
    const panel = dashboard.panels.find(panel => panel.id === 'functions')!
    const page = await panel.load!({ agentId: props.connection.agent_id, search: search.value ?? '', state: 'all',
      offset: 0, limit: 500, signal: request.signal, toolId: props.connection.tool_id })
    if (current !== generation || disposed) return
    entries.value = page.items.flatMap(row => row.children ?? []); warnings.value = page.warnings ?? []
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
watch(() => [props.connection.id, props.connection.agent_id, props.connection.tool_id], () => {
  actionError.value = false
  dashboard.dispose(); dashboard = createPermissionDashboard(t, [], props.connection.id); void load()
})
watch(search, load)
void load()
onBeforeUnmount(() => { disposed = true; generation++; controller?.abort(); dashboard.dispose() })
</script>
