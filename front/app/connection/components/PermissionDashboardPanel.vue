<template>
  <section class="q-mb-xl" :aria-label="t(definition.title)">
    <div class="row items-center q-gutter-sm q-mb-sm">
      <q-icon :name="definition.icon" color="primary" size="sm" />
      <h2 class="text-h6 q-my-none">{{ t(definition.title) }}</h2>
      <q-badge v-if="permitted && !error" color="primary" :label="total" />
      <q-space />
      <q-btn v-if="permitted" flat round color="primary" icon="refresh" :aria-label="t('permissions.refresh')" :loading="loading" @click="emit('changed')" />
    </div>
    <q-banner v-if="!permitted" class="q-mb-md">{{ t('permissions.dashboard.restricted') }}</q-banner>
    <template v-else>
      <div v-if="definition.filterTools && !definition.groupTools" class="row q-mb-md">
        <q-select v-model="toolId" class="col-12 col-md-4" outlined dense emit-value map-options
          :options="[{ value: null, label: t('permissions.dashboard.values.all') }, ...tools]"
          :label="t('connection.tool')" :disable="loading" />
      </div>
      <q-banner v-if="error || actionError" role="alert" class="q-mb-md">{{ t('permissions.error') }}
        <template #action><q-btn outline color="primary" :label="t('permissions.retry')" @click="load" /></template>
      </q-banner>
      <q-banner v-for="warning in warnings" :key="warning" role="status" class="q-mb-sm">{{ warning }}</q-banner>
      <component v-if="definition.component" :is="definition.component" v-bind="definition.componentProps" :agent-id="agentId" :search="search" :state="state" :revision="revision" :customized-only="customizedOnly"
        @answered="emit('changed')" @counts="customCounts" />
      <PermissionToolBrowser v-else-if="definition.groupTools" :entries="rows"
        :filter-key="`${search}:${state}:${customizedOnly}`" :loading="loading" :busy="busy !== null" @change="execute" />
      <PermissionEntryTable v-else v-model:pagination="pagination" :entries="rows" :loading="loading" :busy="busy !== null" @request="requestPage" @change="execute" />
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableProps } from 'quasar'
import { usePrivilegeStore } from '@/core/authorize'
import PermissionEntryTable from './PermissionEntryTable.vue'
import PermissionToolBrowser from './PermissionToolBrowser.vue'
import type { PermissionControl, PermissionCounts, PermissionEntry, PermissionPanelDefinition, PermissionState } from '../services/permissionDashboard'
const props = defineProps<{ definition: PermissionPanelDefinition; agentId: number; search: string; state: PermissionState; revision: number; customizedOnly?: boolean }>()
const emit = defineEmits<{ counts: [counts: PermissionCounts]; customizedCount: [count: number]; changed: [] }>()
const { t } = useI18n()
const authorize = usePrivilegeStore()
const permitted = computed(() => props.definition.privileges.some(code => authorize.hasPrivilege(code)))
const rows = ref<PermissionEntry[]>([]), total = ref(0), warnings = ref<string[]>([])
const tools = ref<{ value: number; label: string }[]>([]), toolId = ref<number | null>(null)
const loading = ref(false), error = ref(false), actionError = ref(false), busy = ref<string | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let controller: AbortController | undefined
let generation = 0, active = true, disposed = false
function customCounts(counts: PermissionCounts) {
  total.value = props.state === 'all' ? Object.values(counts).reduce((sum, count) => sum + (count ?? 0), 0) : counts[props.state] ?? 0
  emit('counts', counts)
  emit('customizedCount', 0)
}
async function load() {
  if (!active || disposed || !permitted.value || !props.definition.load) return
  controller?.abort()
  const request = controller = new AbortController(), current = ++generation
  loading.value = true; error.value = false; actionError.value = false
  try {
    const result = await props.definition.load({ agentId: props.agentId, search: props.search, state: props.state,
      offset: (pagination.value.page - 1) * pagination.value.rowsPerPage, limit: pagination.value.rowsPerPage, signal: request.signal, toolId: toolId.value,
      customizedOnly: props.customizedOnly })
    if (current !== generation || request.signal.aborted) return
    rows.value = result.items; total.value = result.total; warnings.value = result.warnings ?? []; tools.value = result.tools ?? []
    if (toolId.value !== null && !tools.value.some(tool => tool.value === toolId.value)) { toolId.value = null; return }
    pagination.value.rowsNumber = result.total; emit('counts', result.counts); emit('customizedCount', result.customizedCount ?? 0)
  } catch { if (current === generation && !request.signal.aborted) { error.value = true; rows.value = []; emit('counts', {}); emit('customizedCount', 0) } }
  finally { if (current === generation) loading.value = false }
}
async function execute(row: PermissionEntry, control: PermissionControl, value: string) {
  if (busy.value || control.disabled || control.value === value || !control.options.some(option => option.value === value && !option.disable)) return
  const agent = props.agentId
  busy.value = `${row.id}:${control.id}`; actionError.value = false
  try { await control.save(value); if (!disposed && agent === props.agentId) emit('changed') }
  catch { if (!disposed && agent === props.agentId) actionError.value = true }
  finally { if (!disposed) busy.value = null }
}
const requestPage: NonNullable<QTableProps['onRequest']> = ({ pagination: next }) => {
  pagination.value.page = next.page; pagination.value.rowsPerPage = next.rowsPerPage; void load()
}
watch(() => [props.agentId, props.search, props.state, props.customizedOnly, authorize.privileges.join('\0')], () => {
  generation++; controller?.abort(); rows.value = []; pagination.value.page = 1; emit('counts', {}); emit('customizedCount', 0); void load()
})
watch(() => props.revision, () => { generation++; controller?.abort(); void load() })
watch(toolId, () => { pagination.value.page = 1; rows.value = []; emit('counts', {}); void load() })
onMounted(load)
onDeactivated(() => { active = false; generation++; controller?.abort() })
onActivated(() => { if (!active) { active = true; void load() } })
onBeforeUnmount(() => { disposed = true; generation++; controller?.abort() })
</script>
