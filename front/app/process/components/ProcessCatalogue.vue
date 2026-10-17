<template>
  <div>
    <q-banner v-if="error" role="alert" class="q-mb-sm">
      {{ t('nativeProcesses.error') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <q-table
      class="process-table" :rows="rows" :columns="columns" :filter="filter" :loading="loading || externalLoading"
      row-key="key" :grid="$q.screen.lt.md" v-model:pagination="pagination"
      :rows-per-page-options="[10, 20, 50, 100, 500]" :no-data-label="t('processes.noRows')"
    >
      <template #body="scope">
        <q-tr :props="scope" class="process-row" tabindex="0" :aria-expanded="scope.expand"
          :aria-label="t('processes.executions') + ': ' + scope.row.label" @click="scope.expand = !scope.expand"
          @keydown.enter.self="scope.expand = !scope.expand" @keydown.space.self.prevent="scope.expand = !scope.expand">
          <q-td key="label" :props="scope">
            <q-icon :name="scope.expand ? 'expand_less' : 'expand_more'" class="q-mr-sm" aria-hidden="true" />
            <span class="text-weight-medium">{{ scope.row.label }}</span>
            <q-badge v-if="scope.row.native?.archived" outline class="q-ml-sm">{{ t('nativeProcesses.archive') }}</q-badge>
          </q-td>
          <q-td key="tool" :props="scope">{{ scope.row.tool }}</q-td>
          <q-td key="agent" :props="scope">{{ scope.row.agent }}</q-td>
          <q-td key="description" :props="scope" class="process-description">{{ scope.row.description }}</q-td>
          <q-td key="actions" :props="scope">
            <router-link :to="scope.row.editorUrl" class="process-action" :aria-label="t('processes.edit') + ': ' + scope.row.label" @click.stop>
              <q-icon name="edit" color="primary" size="20px" />
              <q-tooltip>{{ t('processes.edit') }}</q-tooltip>
            </router-link>
          </q-td>
        </q-tr>
        <q-tr v-if="scope.expand" :props="scope" :key="`${scope.row.key}-runs`">
          <q-td colspan="100%" class="process-runs-cell">
            <NativeRunsTable v-if="scope.row.native" :code="scope.row.native.code" :refresh-revision="runsRevision" />
            <ExternalProcessRuns v-else :definition="scope.row.external" :revision="runsRevision" @open-run="emit('openRun', $event)" />
          </q-td>
        </q-tr>
      </template>
      <template #item="scope">
        <div class="col-12 q-py-xs">
          <q-card flat bordered>
            <q-card-section class="process-row row items-start no-wrap q-gutter-sm" tabindex="0" role="button"
              :aria-label="t('processes.executions') + ': ' + scope.row.label" :aria-expanded="scope.expand"
              @click="scope.expand = !scope.expand" @keydown.enter.self="scope.expand = !scope.expand"
              @keydown.space.self.prevent="scope.expand = !scope.expand">
              <q-icon :name="scope.expand ? 'expand_less' : 'expand_more'" size="sm" aria-hidden="true" />
              <div class="col process-identity">
                <div class="text-subtitle2">{{ scope.row.label }}</div>
                <q-badge v-if="scope.row.native?.archived" outline>{{ t('nativeProcesses.archive') }}</q-badge>
                <div class="text-caption q-mt-sm">{{ scope.row.tool }}<span v-if="scope.row.agent !== '—'"> · {{ scope.row.agent }}</span></div>
                <div v-if="scope.row.description" class="process-description q-mt-sm">{{ scope.row.description }}</div>
              </div>
              <router-link :to="scope.row.editorUrl" class="process-action" :aria-label="t('processes.edit') + ': ' + scope.row.label" @click.stop>
                <q-icon name="edit" color="primary" size="20px" />
                <q-tooltip>{{ t('processes.edit') }}</q-tooltip>
              </router-link>
            </q-card-section>
            <template v-if="scope.expand">
              <q-separator />
              <q-card-section class="process-runs-cell">
                <NativeRunsTable v-if="scope.row.native" :code="scope.row.native.code" :refresh-revision="runsRevision" />
                <ExternalProcessRuns v-else :definition="scope.row.external" :revision="runsRevision" @open-run="emit('openRun', $event)" />
              </q-card-section>
            </template>
          </q-card>
        </div>
      </template>
    </q-table>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn } from 'quasar'
import { nativeProcessService, type NativeDefinitionSummary } from '../services/nativeProcessService'
import type { AgentOption, ProcessDefinition, ProcessRun, ProcessTool } from '../services/processService'
import NativeRunsTable from './NativeRunsTable.vue'
import ExternalProcessRuns from './ExternalProcessRuns.vue'

const props = defineProps<{
  definitions: ProcessDefinition[]; tools: ProcessTool[]; agents: AgentOption[]
  filter: string | null; externalLoading: boolean; runsRevision: number
}>()
const emit = defineEmits<{ openRun: [run: ProcessRun] }>()
const { t } = useI18n()
const nativeDefinitions = ref<NativeDefinitionSummary[]>([])
const loading = ref(false), error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50 })
let generation = 0
const rows = computed(() => [
  ...nativeDefinitions.value.map(native => ({ key: `native-${native.id}`, label: native.title, tool: 'Galaris', agent: '—', description: '', editorUrl: `/process/internal/${native.code}`, native, external: null })),
  ...props.definitions.map(external => ({ key: `external-${external.id}`, label: external.label,
    tool: props.tools.find(tool => tool.id === external.tool_id)?.label ?? '—',
    agent: props.agents.find(agent => agent.id === external.agent_id)?.label ?? '—', description: external.description ?? '', editorUrl: `/process/external/${external.id}`, native: null, external })),
])
const columns = computed<QTableColumn[]>(() => [
  { name: 'label', label: t('processes.label'), field: 'label', align: 'left', sortable: true },
  { name: 'tool', label: t('processes.tool'), field: 'tool', align: 'left', sortable: true },
  { name: 'agent', label: t('processes.agent'), field: 'agent', align: 'left', sortable: true },
  { name: 'description', label: t('processes.description'), field: 'description', align: 'left', sortable: true },
  { name: 'actions', label: t('processes.actions'), field: 'key', align: 'right' },
])
async function load(): Promise<void> {
  const token = ++generation
  loading.value = true; error.value = false
  try {
    // Both sources share client-side sorting, filtering and pagination; never truncate the native catalogue.
    const first = await nativeProcessService.list(1, 500)
    if (token !== generation) return
    nativeDefinitions.value = first.items
    for (let page = 2; (page - 1) * first.page_size < first.total; page++) {
      const next = await nativeProcessService.list(page, first.page_size)
      if (token !== generation) return
      nativeDefinitions.value.push(...next.items)
    }
  } catch { if (token === generation) error.value = true }
  finally { if (token === generation) loading.value = false }
}
onMounted(load)
onBeforeUnmount(() => { generation++ })
defineExpose({ reload: load })
</script>

<style scoped>
.process-row { cursor: pointer; }
.process-action { display: inline-flex; text-decoration: none; }
.process-action:focus-visible { outline: 2px solid var(--q-primary); outline-offset: 3px; }
.process-row:focus-visible { outline: 2px solid var(--q-primary); outline-offset: -2px; }
.process-identity { min-width: 0; overflow-wrap: anywhere; }
.process-description { white-space: normal; overflow-wrap: anywhere; max-width: 480px; }
.process-runs-cell { padding: 16px; white-space: normal; background: var(--solaire-gray-light); }
body.body--dark .process-runs-cell { background: var(--solaire-gray-dark); }
@media (max-width: 1023px) { .process-runs-cell { padding: 8px; } }
</style>
