<template>
  <q-expansion-item icon="folder_open" :label="t('memory.indexing.title')" @show="open = true; load()" @hide="open = false">
    <q-card flat bordered>
      <q-card-section>
        <q-form v-if="editable" class="row items-center q-gutter-sm" @submit="start">
          <q-input v-model="root" class="col" outlined dense :label="t('memory.indexing.root')" />
          <q-btn type="submit" :loading="busy" :disable="!root.trim()" :label="t('memory.indexing.start')" />
        </q-form>
        <div v-if="error" role="alert" class="q-mt-sm">{{ t('memory.indexing.error') }}</div>
        <q-btn v-if="error" flat :label="t('common.retry')" @click="load" />
        <p v-if="data" class="q-mt-sm">{{ t('memory.indexing.repairs', { pending: data.pending_repairs, failed: data.failed_repairs }) }}</p>
        <q-btn v-if="editable && data?.failed_repairs" flat :label="t('memory.indexing.retryRepairs')" @click="retryRepairs" />
        <q-table v-if="data" :rows="data.runs" :columns="columns" row-key="id" :loading="loading"
          v-model:pagination="pagination" :rows-per-page-options="[10, 20, 50, 100, 500]"
          :no-data-label="t('memory.indexing.empty')" @request="requested">
          <template #body-cell-status="props"><q-td :props="props">{{ t(`memory.indexing.status.${props.row.status}`) }}</q-td></template>
          <template #body-cell-actions="props"><q-td :props="props">
            <q-btn v-if="editable && ['queued', 'running', 'retry'].includes(props.row.status)" flat
              :label="t('common.cancel')" @click="cancel(props.row.id)" />
          </q-td></template>
        </q-table>
      </q-card-section>
    </q-card>
  </q-expansion-item>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn } from 'quasar'
import { fileIndexService, type FileIndexPage } from '../services/fileIndexService'
const { agentId, editable } = defineProps<{ agentId: number; editable: boolean }>()
const { t } = useI18n()
const root = ref(''), open = ref(false), busy = ref(false), loading = ref(false), error = ref(false)
const data = ref<FileIndexPage | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
let disposed = false
const columns = computed<QTableColumn[]>(() => [
  { name: 'root', label: t('memory.indexing.root'), field: 'root_uri', align: 'left' },
  { name: 'status', label: t('memory.indexing.state'), field: 'status', align: 'left' },
  { name: 'scanned', label: t('memory.indexing.scanned'), field: 'scanned', align: 'right' },
  { name: 'directories', label: t('memory.indexing.directories'), field: 'directories', align: 'right' },
  { name: 'error', label: t('memory.indexing.failure'), field: 'error_type', align: 'left' },
  { name: 'actions', label: '', field: 'id' },
])
async function load() {
  if (loading.value || !open.value) return
  const token = ++generation, owner = agentId
  loading.value = true
  try {
    const result = await fileIndexService.list(owner, pagination.value.page, pagination.value.rowsPerPage)
    if (disposed || token !== generation || owner !== agentId) return
    data.value = result
    pagination.value.rowsNumber = result.total
    error.value = false
  } catch { if (token === generation) error.value = true }
  finally { if (token === generation) loading.value = false }
}
async function start() {
  const owner = agentId
  busy.value = true
  try { await fileIndexService.start(owner, root.value.trim()); if (owner === agentId) await load() }
  catch { if (owner === agentId) error.value = true }
  finally { busy.value = false }
}
async function cancel(id: string) {
  const owner = agentId
  try { await fileIndexService.cancel(owner, id); if (owner === agentId) await load() }
  catch { if (owner === agentId) error.value = true }
}
async function retryRepairs() {
  const owner = agentId
  try { await fileIndexService.retryRepairs(owner); if (owner === agentId) await load() }
  catch { if (owner === agentId) error.value = true }
}
function requested({ pagination: next }: { pagination: { page: number; rowsPerPage: number } }) {
  pagination.value = { ...pagination.value, ...next }
  void load()
}
watch(() => agentId, () => { generation++; data.value = null; root.value = ''; loading.value = false; pagination.value.page = 1; void load() })
const timer = setInterval(() => { if (open.value) void load() }, 5000)
onBeforeUnmount(() => { disposed = true; generation++; clearInterval(timer) })
</script>
