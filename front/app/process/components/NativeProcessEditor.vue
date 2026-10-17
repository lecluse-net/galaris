<template>
  <div>
    <PageHeader :icon="navigationIcon('account_tree')" :title="t('nativeProcesses.editor')">
      <template #title-after>
        <q-badge v-if="definition">{{ definition.code }}</q-badge>
        <q-badge v-if="definition?.archived" color="warning">{{ t('nativeProcesses.archived') }}</q-badge>
        <q-badge v-if="definition && !editable" outline>{{ t('nativeProcesses.readOnly') }}</q-badge>
      </template>
    </PageHeader>
    <div class="row q-mb-md">
      <q-btn color="warning" icon="arrow_back" :label="t('processes.backToList')" to="/process" />
    </div>
    <div class="editor-content">
      <q-banner v-if="error" role="alert">{{ error }}<template #action><q-btn flat :label="t('nativeProcesses.retry')" @click="sharingPending ? save() : load()" /></template></q-banner>
      <q-spinner v-if="loading" />
      <template v-else-if="definition || !code">
        <div class="row q-col-gutter-md">
          <div class="col-12 col-md-6">
            <q-input v-model="title" outlined dense hide-bottom-space :readonly="!editable" :label="t('nativeProcesses.titleField')" />
          </div>
          <div class="col-12 col-md-6">
            <MemorySharingPanel v-if="definition && !sharingPending" :item-id="definition.document_id" resource-kind="document" :editable="editable" :reader="readSharing" :writer="writeSharing" />
            <template v-else>
            <ProcessSharingDraft v-model="sharingDraft" :agent-id="launcherAgentId" :owner="owner" :editable="editable && !saving" />
            <div v-if="!definition" class="row q-col-gutter-sm q-mt-sm">
              <div :class="owner === 'agent' ? 'col-12 col-sm-6' : 'col-12'">
                <q-select v-model="owner" outlined dense hide-bottom-space :options="ownerOptions" emit-value map-options :readonly="!editable" :label="t('nativeProcesses.owner')" />
              </div>
              <div v-if="owner === 'agent'" class="col-12 col-sm-6">
                <ProcessAgentSelect v-model="launcherAgentId" :options="agents" outlined dense hide-bottom-space :readonly="!editable" :label="t('nativeProcesses.ownerAgent')" />
              </div>
            </div>
            </template>
          </div>
        </div>
        <q-banner v-if="sharingPending && !saving" role="status">{{ t('nativeProcesses.sharingPending') }}</q-banner>
        <q-input v-model="description" outlined dense hide-bottom-space :readonly="!editable" :label="t('nativeProcesses.description')" />
        <q-banner v-if="graph.schema_version === 'galaris.bpmn/v1'">
          {{ t('nativeProcesses.variables.legacy') }}
          <template v-if="editable" #action><q-btn flat :label="t('nativeProcesses.variables.upgrade')" @click="upgradeProfile" /></template>
        </q-banner>
        <q-banner v-for="diagnostic in definition?.diagnostics" :key="diagnostic.node + diagnostic.code">{{ diagnostic.node }} · {{ t(diagnostic.code === 'isolated_runner_unavailable' ? 'nativeProcesses.codeUnavailable' : 'nativeProcesses.programUnavailable') }}</q-banner>
        <div class="editor-workspace">
          <div class="editor-diagram">
            <q-breadcrumbs v-if="bodyPath.length" class="q-mb-sm"><q-breadcrumbs-el :label="title || t('nativeProcesses.editor')" @click="bodyPath = []" />
              <q-breadcrumbs-el v-for="(key, index) in bodyPath" :key="key" :label="key" @click="bodyPath = bodyPath.slice(0, index + 1)" /></q-breadcrumbs>
            <BpmnCanvas v-model="localGraph" v-model:execution-agent-id="executionAgentId" :execution-editable="editable" :readonly="!editable" :selected="selectedNode" :selected-flow="selectedFlow" :agents="agents" :humans="humans" :humans-loading="humansLoading" :humans-error="humansError" @reload-humans="loadHumans" @select="selectNode" @flow="selectFlow" @remove="removeNode" @dismiss="dismissInspector">
              <template v-if="editable" #toolbar-actions>
                <q-btn color="primary" icon="save" :label="t('nativeProcesses.save')" :loading="saving" :disable="archiving" @click="save" />
                <q-btn outline color="positive" icon="fact_check" :label="t('nativeProcesses.validate')" @click="validate" />
                <q-btn v-if="definition" :outline="!definition.archived" :color="definition.archived ? 'positive' : 'negative'"
                  :icon="definition.archived ? 'unarchive' : 'archive'" :label="t(definition.archived ? 'nativeProcesses.reactivate' : 'nativeProcesses.archive')"
                  :loading="archiving" :disable="saving" @click="requestArchive" />
              </template>
              <template #inspector>
                <div v-if="selected || flowSelected" class="editor-inspector q-gutter-y-sm">
                  <div class="row items-center no-wrap q-gutter-x-sm">
                    <span class="col-auto">{{ selected ? t('nativeProcesses.kinds.' + selected.kind) : t('nativeProcesses.flowSettings') }}</span>
                    <q-select v-if="modeEditable && currentMode !== 'human'" :model-value="selected?.kind === 'if' && !selected.config.mode ? null : currentMode" :options="processingOptions"
                      class="col" dense outlined emit-value map-options :readonly="!editable" :label="t('nativeProcesses.processingMode')" @update:model-value="setProcessingMode" />
                    <q-space v-else />
                    <q-btn flat round dense icon="close" :aria-label="t('nativeProcesses.closeSettings')" @click="selectedNode = null; selectedFlow = null" />
                  </div>
                  <template v-if="selected">
                    <q-select v-if="contractActivity && !['task', 'human_task', 'code'].includes(selected.kind)" :model-value="configString('actor') || null" :options="actorOptions"
                      emit-value map-options outlined clearable :readonly="!editable" :label="t('nativeProcesses.taskActor')" @update:model-value="setActor" />
                    <q-input :model-value="selected.title" outlined :readonly="!editable" :label="t('nativeProcesses.nodeTitle')" @update:model-value="setTitle" />
                    <template v-if="localGraph.schema_version === 'galaris.bpmn/v2'">
                      <ProcessVariableDeclarations v-if="contractActivity || selected.kind === 'start'" :key="`${selected.id}-inputs`"
                        :model-value="selected.kind === 'start' ? localGraph.inputs ?? [] : selected.inputs ?? []" :readonly="!editable"
                        :draft-values="declarationDrafts[`${selected.id}:inputs`]" @update:draft-values="declarationDrafts[`${selected.id}:inputs`] = $event"
                        :label="t('nativeProcesses.variables.inputs')" @update:model-value="setDeclarations('inputs', $event)"
                        @validity="invalidDrafts[`${selected.id}:inputs`] = !$event" />
                      <ProcessVariableDeclarations v-if="contractActivity || selected.kind === 'end'" :key="`${selected.id}-outputs`"
                        :model-value="selected.kind === 'end' ? localGraph.outputs ?? [] : selected.outputs ?? []" :readonly="!editable"
                        :draft-values="declarationDrafts[`${selected.id}:outputs`]" @update:draft-values="declarationDrafts[`${selected.id}:outputs`] = $event"
                        :label="t('nativeProcesses.variables.outputs')" @update:model-value="setDeclarations('outputs', $event)"
                        @validity="invalidDrafts[`${selected.id}:outputs`] = !$event" />
                    </template>
                    <q-input v-if="selected.kind === 'task' || selected.kind === 'human_task' || selected.kind === 'if' && selected.config.mode && currentMode !== 'code'" :model-value="configString('prompt')" outlined type="textarea" autogrow :readonly="!editable" :label="t('nativeProcesses.instructions')" @update:model-value="setConfig('prompt', String($event ?? ''))" />
                    <q-input v-if="selected.kind === 'for'" :model-value="configString('items')" outlined :readonly="!editable" :label="t('nativeProcesses.items')" @update:model-value="setConfig('items', String($event ?? ''))" />
                    <q-input v-if="selected.kind === 'while'" :model-value="configString('condition')" outlined :readonly="!editable" :label="t('nativeProcesses.whileCondition')" @update:model-value="setConfig('condition', String($event ?? ''))" />
                    <q-input v-if="selected.kind === 'call'" :model-value="configString('process_code')" outlined :readonly="!editable" :label="t('nativeProcesses.processCode')" @update:model-value="setConfig('process_code', String($event ?? ''))" />
                    <CodeEditor v-if="selected.kind === 'code' || selected.kind === 'if' && currentMode === 'code'" :key="`${selected.id}-code`" :model-value="configString('code')" language="python" :readonly="!editable" :label="t('nativeProcesses.pythonCode')" @update:model-value="setConfig('code', $event)" />
                    <q-input v-if="selected.kind === 'tool_call'" :model-value="configString('tool')" outlined :readonly="!editable" :label="t('nativeProcesses.tool')" @update:model-value="setConfig('tool', String($event ?? ''))" />
                    <template v-if="selected.kind === 'rest'">
                      <q-input :model-value="configString('tool_code')" outlined :readonly="!editable" :label="t('nativeProcesses.restTool')" @update:model-value="setConfig('tool_code', String($event ?? ''))" />
                      <CodeEditor :key="`${selected.id}-request`" :model-value="configJson('request')" language="json" :readonly="!editable" :label="t('nativeProcesses.restRequest')" @update:model-value="setConfigJson('request', $event)" />
                    </template>
                    <q-btn v-if="selected.body" flat icon="open_in_new" :label="t('nativeProcesses.openBody')" @click="openBody" />
                    <CodeEditor v-if="(selected.kind === 'tool_call' || selected.kind === 'program') && localGraph.schema_version === 'galaris.bpmn/v1'" :key="`${selected.id}-input`" :model-value="configJson('input')" language="json" :readonly="!editable" :label="t('nativeProcesses.toolArguments')" @update:model-value="setConfigJson('input', $event)" />
                    <template v-if="contractActivity && !modeEditable && localGraph.schema_version === 'galaris.bpmn/v2'">
                      <CodeEditor :key="`${selected.id}-mapping`" :model-value="configJson('input_mapping')" language="json" :readonly="!editable" :label="t('nativeProcesses.variables.mapping')" @update:model-value="setConfigJson('input_mapping', $event)" />
                      <template v-if="selected.kind === 'tool_call' || selected.kind === 'rest' || selected.kind === 'call'">
                        <CodeEditor :key="`${selected.id}-external`" :model-value="configJson('external_output')" language="json" :readonly="!editable" :label="t('nativeProcesses.variables.externalOutput')" @update:model-value="setConfigJson('external_output', $event)" />
                        <q-checkbox :model-value="selected.config.external_output_typed === true" :disable="!editable" :label="t('nativeProcesses.variables.externalTyped')" @update:model-value="setConfig('external_output_typed', Boolean($event))" />
                      </template>
                      <template v-for="phase in ['preprocess', 'postprocess'] as const" :key="`${selected.id}-${phase}`">
                        <q-checkbox :model-value="selected.config[phase] !== undefined" :disable="!editable" :label="t(`nativeProcesses.${phase}`)" @update:model-value="toggleScript(phase, Boolean($event))" />
                        <CodeEditor v-if="selected.config[phase] !== undefined" :model-value="configString(phase)" language="python" :readonly="!editable" :label="t(`nativeProcesses.${phase}`)" @update:model-value="setConfig(phase, $event)" />
                      </template>
                    </template>
                    <div v-for="flow in selected.kind === 'if' && !selected.config.mode ? outgoing : []" :key="flow.id">
                      <div class="text-caption">{{ flow.target }}</div><q-input :model-value="flow.condition ?? ''" outlined :readonly="!editable" :label="t('nativeProcesses.condition')" @update:model-value="setFlowCondition(flow.id, $event)" />
                    </div>
                    <q-btn v-if="editable && selected.kind !== 'start' && (selected.kind !== 'end' || localGraph.nodes.filter(node => node.kind === 'end').length > 1)" color="negative" icon="delete_outline" :label="t('nativeProcesses.removeNode')" @click="removeNode(selected.id)" />
                  </template>
                  <template v-if="flowSelected">
                    <q-select :model-value="flowSelected.source" :options="flowSourceOptions" emit-value map-options outlined :readonly="!editable" :label="t('nativeProcesses.flowSource')" @update:model-value="setFlowEndpoint('source', $event)" />
                    <q-select :model-value="flowSelected.target" :options="flowTargetOptions" emit-value map-options outlined :readonly="!editable" :label="t('nativeProcesses.flowTarget')" @update:model-value="setFlowEndpoint('target', $event)" />
                    <q-input v-if="localGraph.nodes.find(node => node.id === flowSelected?.source)?.kind === 'if' && !localGraph.nodes.find(node => node.id === flowSelected?.source)?.config.mode" :model-value="flowSelected.condition ?? ''" outlined :readonly="!editable" :label="t('nativeProcesses.condition')" @update:model-value="setFlowCondition(flowSelected.id, $event)" />
                    <q-btn v-if="editable" color="negative" icon="delete_outline" :label="t('nativeProcesses.removeFlow')" @click="removeFlow" />
                  </template>
                </div>
              </template>
            </BpmnCanvas>
          </div>
        </div>
        <template v-if="definition">
          <q-expansion-item :label="t('nativeProcesses.history')" icon="history" @show="loadHistory()">
            <q-banner v-if="historyError" role="alert">
              {{ t('nativeProcesses.error') }}
              <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="loadHistory(historyRequest.page, historyRequest.rowsPerPage)" /></template>
            </q-banner>
            <div class="history-workspace">
            <q-table class="history-list" bordered flat wrap-cells hide-header :rows="history?.items ?? []" :columns="historyColumns" row-key="revision"
              :aria-label="t('nativeProcesses.history')" :loading="historyLoading" v-model:pagination="historyPagination"
              :rows-per-page-options="[10, 20, 50, 100, 500]" :rows-per-page-label="t('nativeProcesses.historyPageSize')"
              :pagination-label="(first, last, total) => t('nativeProcesses.historyRange', { first, last, total })"
              :no-data-label="t('nativeProcesses.historyEmpty')" @request="requestHistoryPage">
              <template #body-cell-revision="scope">
                <q-td :props="scope" class="history-revision-cell" :class="{ 'history-revision-selected': selectedRevision === scope.row.revision }">
                  <q-item clickable class="q-px-sm" role="button" :aria-label="formatRevisionDate(scope.row.created_at)" :aria-pressed="selectedRevision === scope.row.revision" :active="selectedRevision === scope.row.revision" @click="viewRevision(scope.row.revision)">
                    <q-item-section>
                      <q-item-label>{{ formatRevisionDate(scope.row.created_at) }}</q-item-label>
                    </q-item-section>
                    <q-item-section side>
                      <div class="row q-gutter-sm no-wrap">
                        <q-btn v-if="editable && scope.row.revision !== definition.revision" round dense color="primary" icon="restore" :aria-label="t('nativeProcesses.restore')" :disable="saving || deletingRevision" @click.stop="requestRevisionAction('restore', scope.row)" @keydown.stop @keyup.stop>
                          <q-tooltip>{{ t('nativeProcesses.restore') }}</q-tooltip>
                        </q-btn>
                        <q-btn v-if="editable && scope.row.revision !== definition.revision" outline round dense color="negative" icon="delete_outline" :aria-label="t('nativeProcesses.deleteRevision')" :disable="saving || deletingRevision" @click.stop="requestRevisionAction('delete', scope.row)" @keydown.stop @keyup.stop>
                          <q-tooltip>{{ t('nativeProcesses.deleteRevision') }}</q-tooltip>
                        </q-btn>
                      </div>
                    </q-item-section>
                  </q-item>
                </q-td>
              </template>
            </q-table>
            <section class="history-comparison" :aria-label="t('nativeProcesses.historyComparison')" :aria-busy="revisionLoading">
              <div v-if="revisionLoading" class="history-state"><q-spinner color="primary" size="32px" /></div>
              <q-banner v-else-if="revisionError" role="alert">
                {{ t('nativeProcesses.error') }}
                <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="selectedRevision !== null && viewRevision(selectedRevision)" /></template>
              </q-banner>
              <div v-else-if="pastRevision">
                <BpmnCanvas :key="`${pastRevision.revision}-saved`" :model-value="pastRevision.graph" readonly :show-guide="false" :agents="agents" :humans="humans" />
              </div>
              <div v-else class="history-state text-body2">{{ t('nativeProcesses.historySelect') }}</div>
            </section>
            </div>
          </q-expansion-item>
          <NativeRunsTable :code="definition.code" />
        </template>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useQuasar, type QTableColumn } from 'quasar'
import { usePrivilegeStore } from '@/core/authorize'
import { navigationIcon } from '@/core/navigation'
import { CodeEditor, PageHeader, showConfirmationDialog, type SharingDraft } from '@/core/util'
import { MemorySharingPanel, type DocumentSharing, type DocumentSharingLevelUpdate } from '@/app/memory'
import BpmnCanvas from './BpmnCanvas.vue'
import NativeRunsTable from './NativeRunsTable.vue'
import ProcessAgentSelect from './ProcessAgentSelect.vue'
import ProcessSharingDraft from './ProcessSharingDraft.vue'
import ProcessVariableDeclarations from './ProcessVariableDeclarations.vue'
import { persistLayout, processingMode, defaultDecisionCode, defaultTaskCode } from '../graphEditing'
import { emptyGraph, nativeProcessService as service, type BpmnGraph, type BpmnNode, type NativeDefinition, type ProcessHistory, type ProcessAgentOption, type ProcessVariable } from '../services/nativeProcessService'
const props = withDefaults(defineProps<{ code?: string | null }>(), { code: null })
const { t, locale } = useI18n(), router = useRouter(), $q = useQuasar(), privileges = usePrivilegeStore()
const definition = shallowRef<NativeDefinition | null>(null), graph = shallowRef(emptyGraph()), title = ref('')
const description = ref('')
const agents = ref<ProcessAgentOption[]>([]), launcherAgentId = ref<number | null>(null), owner = ref<'user' | 'agent'>('user')
const humans = ref<{ id: number; label: string }[]>([])
const sharingDraft = ref<SharingDraft>({ level: 'private', can_write: false, grants: [] })
const sharingPending = ref(false)
const humansLoading = ref(false), humansError = ref(false)
let humansRequest: AbortController | null = null
const loading = ref(false), saving = ref(false), archiving = ref(false), error = ref('')
let archiveDialog: ReturnType<typeof showConfirmationDialog> | null = null
let revisionDialog: ReturnType<typeof showConfirmationDialog> | null = null
const deletingRevision = ref(false)
const selectedNode = ref<string | null>(null), selectedFlow = ref<string | null>(null), bodyPath = ref<string[]>([])
const history = ref<ProcessHistory | null>(null)
const historyPagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const historyLoading = ref(false), historyError = ref(false)
let historyGeneration = 0, historyRequest = { page: 1, rowsPerPage: 50 }
const historyColumns = computed<QTableColumn[]>(() => [
  { name: 'revision', label: t('nativeProcesses.historyRevision'), field: 'revision', align: 'left', format: value => t('nativeProcesses.revision', { revision: value }) },
])
const pastRevision = shallowRef<{ revision: number; graph: BpmnGraph } | null>(null)
const selectedRevision = ref<number | null>(null), revisionLoading = ref(false), revisionError = ref(false)
const invalidDrafts = ref<Record<string, boolean>>({})
const drafts = ref<Record<string, string>>({})
const declarationDrafts = ref<Record<string, Record<number, string>>>({})
let generation = 0, revisionGeneration = 0
const editable = computed(() => (privileges.hasPrivilege('PROCESS_EDIT') || privileges.hasPrivilege('PROCESS_ADMIN')) && (!props.code || Boolean(definition.value?.can_write)))
const executionAgentId = computed({
  get: () => graph.value.execution_agent_id ?? null,
  set: (id: number | null) => { if (editable.value) graph.value = { ...graph.value, execution_agent_id: id } },
})
const humanSourceAgentId = computed(() => executionAgentId.value ?? launcherAgentId.value)
function clearHumans(): void {
  humansRequest?.abort(); humansRequest = null
  humans.value = []; humansLoading.value = false; humansError.value = false
}
async function loadHumans(): Promise<void> {
  const agentId = humanSourceAgentId.value
  if (!editable.value || loading.value || agentId === null || humansRequest) return
  const request = new AbortController()
  humansRequest = request; humansLoading.value = true; humansError.value = false
  try {
    const options = await service.humans(agentId, request.signal)
    if (humansRequest === request && humanSourceAgentId.value === agentId && editable.value) humans.value = options
  } catch {
    if (humansRequest === request && !request.signal.aborted) { humans.value = []; humansError.value = true }
  } finally {
    if (humansRequest === request) { humansRequest = null; humansLoading.value = false }
  }
}
const ownerOptions = computed(() => [{ value: 'user', label: t('nativeProcesses.userOwner') }, { value: 'agent', label: t('nativeProcesses.agentOwner') }])
function atPath(root: BpmnGraph, path: string[]): BpmnGraph { let current = root; for (const key of path) { const body = current.nodes.find(node => node.id === key)?.body; if (!body) break; current = body } return current }
const localGraph = computed<BpmnGraph>({ get: () => atPath(graph.value, bodyPath.value), set: value => {
  function replace(root: BpmnGraph, path: string[]): BpmnGraph {
    if (!path.length) return value
    return { ...root, nodes: root.nodes.map(node => node.id === path[0] && node.body ? { ...node, body: replace(node.body, path.slice(1)) } : node) }
  }
  graph.value = replace(graph.value, bodyPath.value)
} })
const selected = computed(() => localGraph.value.nodes.find(node => node.id === selectedNode.value))
const modeEditable = computed(() => localGraph.value.schema_version === 'galaris.bpmn/v2' && selected.value && ['task', 'human_task', 'code', 'if'].includes(selected.value.kind))
const currentMode = computed(() => selected.value ? processingMode(selected.value, localGraph.value) : 'ai')
const processingOptions = computed(() => ['ai', 'code'].map(value => ({ value, label: t('nativeProcesses.processingModes.' + value) })))
function setProcessingMode(value: unknown): void {
  if (!editable.value || !modeEditable.value || currentMode.value === 'human' || value !== 'ai' && value !== 'code') return
  const converting = selected.value?.kind === 'if' && !selected.value.config.mode ? selected.value.id : null
  editNode(node => {
    const config: Record<string, unknown> = { prompt: '', ...node.config }
    if (node.kind === 'if') return { ...node, config: { ...config, mode: value, code: config.code ?? defaultDecisionCode } }
    return { ...node, kind: value === 'code' ? 'code' : 'task', config: { ...config, code: config.code ?? defaultTaskCode, ...(value === 'code' ? { dataset_code: true } : {}) } }
  })
  if (converting) {
    const links = localGraph.value.flows.filter(flow => flow.source === converting)
    if (links.length && links.length <= 2) {
      const positive = links.find(flow => flow.condition !== null) ?? links[0]!
      const flows = localGraph.value.flows.map(flow => flow.source === converting ? { ...flow, condition: flow.id === positive.id ? 'decision' : null } : flow)
      if (links.length === 1) flows.push({ id: 'flow_' + crypto.randomUUID().replaceAll('-', ''), source: converting, target: positive.target, condition: null })
      localGraph.value = { ...localGraph.value, flows }
    }
  }
}
const contractActivity = computed(() => Boolean(selected.value && ['task', 'human_task', 'tool_call', 'rest', 'code', 'program', 'call'].includes(selected.value.kind)))
function toggleScript(phase: 'preprocess' | 'postprocess', enabled: boolean): void { editNode(node => { const config = { ...node.config }; if (enabled) config[phase] = ''; else delete config[phase]; return { ...node, config } }) }
function setDeclarations(side: 'inputs' | 'outputs', values: ProcessVariable[]): void {
  if (!editable.value || !selected.value) return
  if (selected.value.kind === 'start' || selected.value.kind === 'end') localGraph.value = { ...localGraph.value, [side]: values }
  else editNode(node => ({ ...node, [side]: values }))
}
function upgradeProfile(): void {
  if (!editable.value) return
  function upgrade(value: BpmnGraph): BpmnGraph { return { ...value, schema_version: 'galaris.bpmn/v2', inputs: [], outputs: [], nodes: value.nodes.map(node => ({ ...node,
    ...(['task', 'human_task', 'tool_call', 'rest', 'code', 'program', 'call'].includes(node.kind) ? { inputs: [], outputs: [] } : {}), body: node.body ? upgrade(node.body) : null })) } }
  graph.value = upgrade(graph.value)
}
const actorOptions = computed(() => (localGraph.value.actors ?? []).filter(actor => actor.kind === (selected.value?.kind === 'human_task' ? 'human' : 'agent')).map(actor => ({ value: actor.id, label: actor.name })))
const flowSourceOptions = computed(() => localGraph.value.nodes.filter(node => node.kind !== 'end' && node.id !== flowSelected.value?.target).map(node => ({ value: node.id, label: node.title || t('nativeProcesses.kinds.' + node.kind) })))
const flowTargetOptions = computed(() => localGraph.value.nodes.filter(node => node.kind !== 'start' && node.id !== flowSelected.value?.source).map(node => ({ value: node.id, label: node.title || t('nativeProcesses.kinds.' + node.kind) })))
function setActor(value: unknown): void { if (typeof value === 'string' || value === null) { if (typeof value === 'string' && !actorOptions.value.some(actor => actor.value === value)) return; setConfig('actor', value) } }
function setFlowEndpoint(side: 'source' | 'target', value: unknown): void { if (editable.value && typeof value === 'string') localGraph.value = { ...localGraph.value, flows: localGraph.value.flows.map(flow => flow.id === selectedFlow.value ? { ...flow, [side]: value } : flow) } }
const flowSelected = computed(() => localGraph.value.flows.find(flow => flow.id === selectedFlow.value))
const outgoing = computed(() => localGraph.value.flows.filter(flow => flow.source === selectedNode.value))
function report(cause: unknown): void {
  const response = cause as { response?: { data?: { detail?: unknown } } }
  error.value = typeof response.response?.data?.detail === 'string' ? response.response.data.detail : cause instanceof Error ? cause.message : t('nativeProcesses.error')
}
function apply(value: NativeDefinition): void { definition.value = value; graph.value = value.graph; title.value = value.title; description.value = value.description ?? ''; bodyPath.value = []; selectedNode.value = null; selectedFlow.value = null; invalidDrafts.value = {}; drafts.value = {}; declarationDrafts.value = {}; pastRevision.value = null; selectedRevision.value = null; revisionLoading.value = false; revisionError.value = false; revisionGeneration++; error.value = '' }
async function load(): Promise<void> {
  const token = ++generation, code = props.code
  sharingPending.value = false; sharingDraft.value = { level: 'private', can_write: false, grants: [] }
  loading.value = true; error.value = ''; definition.value = null; history.value = null; pastRevision.value = null; revisionGeneration++; drafts.value = {}; invalidDrafts.value = {}
  selectedRevision.value = null; revisionLoading.value = false; revisionError.value = false
  historyGeneration++; historyLoading.value = false; historyError.value = false
  historyPagination.value = { page: 1, rowsPerPage: 50, rowsNumber: 0 }; historyRequest = { page: 1, rowsPerPage: 50 }
  declarationDrafts.value = {}
  try {
    if (code) { const value = await service.get(code); if (token !== generation) return; apply(value) }
    else { graph.value = emptyGraph(); title.value = ''; description.value = ''; bodyPath.value = [] }
    const options = await service.agents(); if (token !== generation) return; agents.value = options; launcherAgentId.value = options[0]?.id ?? null
  } catch (cause) { if (token === generation) report(cause) }
  finally { if (token === generation) loading.value = false }
}
function selectNode(id: string): void { selectedNode.value = id; selectedFlow.value = null }
function readSharing(_id: string): Promise<DocumentSharing> { return service.sharing(definition.value?.code ?? '') }
function writeSharing(_id: string, value: DocumentSharingLevelUpdate): Promise<DocumentSharing> { return service.share(definition.value?.code ?? '', value) }
function selectFlow(id: string): void { selectedFlow.value = id; selectedNode.value = null }
function dismissInspector(kind: 'node' | 'flow', id: string): void {
  if (kind === 'node' && selectedNode.value === id) selectedNode.value = null
  if (kind === 'flow' && selectedFlow.value === id) selectedFlow.value = null
}
function editNode(update: (node: BpmnNode) => BpmnNode): void { if (!editable.value || !selected.value) return; localGraph.value = { ...localGraph.value, nodes: localGraph.value.nodes.map(node => node.id === selectedNode.value ? update(node) : node) } }
function configString(key: string): string { return String(selected.value?.config[key] ?? '') }
function configJson(key: string): string { return drafts.value[selectedNode.value + ':' + key] ?? JSON.stringify(selected.value?.config[key] ?? (key === 'external_output' ? { $expr: 'result' } : key === 'request' ? { method: 'GET', path: '' } : { $expr: 'data' }), null, 2) }
function setTitle(value: unknown): void { editNode(node => ({ ...node, title: String(value ?? '') })) }
function setConfig(key: string, value: unknown): void { editNode(node => ({ ...node, config: { ...node.config, [key]: value } })) }
function setConfigJson(key: string, value: string): void { if (!editable.value) return; const id = selectedNode.value + ':' + key; drafts.value[id] = value; try { setConfig(key, JSON.parse(value)); invalidDrafts.value[id] = false } catch { invalidDrafts.value[id] = true } }
function assertDrafts(): void { if (Object.values(invalidDrafts.value).some(Boolean)) throw new Error(t('processes.invalidJson')) }
function setFlowCondition(id: string, value: unknown): void { if (editable.value) localGraph.value = { ...localGraph.value, flows: localGraph.value.flows.map(flow => flow.id === id ? { ...flow, condition: String(value ?? '').trim() || null } : flow) } }
function removeFlow(): void { if (editable.value) localGraph.value = { ...localGraph.value, flows: localGraph.value.flows.filter(flow => flow.id !== selectedFlow.value) }; selectedFlow.value = null }
function removeNode(id: string): void {
  const node = localGraph.value.nodes.find(node => node.id === id)
  if (!editable.value || node?.kind === 'start' || node?.kind === 'end' && localGraph.value.nodes.filter(node => node.kind === 'end').length <= 1) return
  localGraph.value = { ...localGraph.value, nodes: localGraph.value.nodes.filter(node => node.id !== id), flows: localGraph.value.flows.filter(flow => flow.source !== id && flow.target !== id) }
  for (const key of Object.keys(drafts.value)) if (key.startsWith(id + ':')) { delete drafts.value[key]; delete invalidDrafts.value[key] }
  selectedNode.value = null
}
function openBody(): void { if (!selected.value?.body) return; bodyPath.value = [...bodyPath.value, selected.value.id]; selectedNode.value = null }
async function validate(): Promise<void> { const token = generation; try { assertDrafts(); await service.validate({ graph: persistLayout(graph.value) }); if (token !== generation) return; error.value = ''; $q.notify({ message: t('nativeProcesses.valid'), color: 'positive' }) } catch (cause) { if (token === generation) report(cause) } }
async function save(): Promise<void> {
  if (!editable.value || saving.value || archiving.value || !launcherAgentId.value && !definition.value) return
  const token = generation
  saving.value = true
  try {
    assertDrafts()
    const creating = !definition.value
    const result = definition.value ? await service.save(definition.value.code, { title: title.value, description: description.value, expected_revision: definition.value.revision,
      graph: persistLayout(graph.value) }) : await service.create({ title: title.value, description: description.value,
        graph: persistLayout(graph.value), agent_id: launcherAgentId.value!, owner: owner.value })
    if (token !== generation) return
    definition.value = result
    if (creating) sharingPending.value = true
    if (sharingPending.value) {
      const state = await service.sharing(result.code)
      if (token !== generation) return
      await service.share(result.code, { ...sharingDraft.value, expected_lock_version: state.lock_version })
      if (token !== generation) return
      sharingPending.value = false
    }
    apply(result); $q.notify({ message: t('nativeProcesses.saved'), color: 'positive' })
    if (!props.code) await router.replace(`/process/internal/${result.code}`)
  } catch (cause) { if (token === generation) report(cause) } finally { if (token === generation) saving.value = false }
}
async function loadHistory(page = historyPagination.value.page, rowsPerPage = historyPagination.value.rowsPerPage): Promise<void> {
  if (!props.code) return
  const token = generation, request = ++historyGeneration
  historyRequest = { page, rowsPerPage }; historyLoading.value = true; historyError.value = false
  try {
    const result = await service.history(props.code, page, rowsPerPage)
    if (token !== generation || request !== historyGeneration) return
    history.value = result; historyPagination.value = { page, rowsPerPage, rowsNumber: result.total }
  } catch {
    if (token === generation && request === historyGeneration) historyError.value = true
  } finally {
    if (token === generation && request === historyGeneration) historyLoading.value = false
  }
}
function requestHistoryPage(request: { pagination: { page: number; rowsPerPage: number } }): void {
  void loadHistory(request.pagination.page, request.pagination.rowsPerPage)
}
async function viewRevision(revision: number): Promise<void> {
  if (!props.code) return
  const token = generation, request = ++revisionGeneration
  pastRevision.value = null; selectedRevision.value = revision; revisionLoading.value = true; revisionError.value = false
  try {
    const result = await service.revision(props.code, revision)
    if (token !== generation || request !== revisionGeneration) return
    const parsed = await service.validate({ xml: result.detail.content })
    if (token === generation && request === revisionGeneration) pastRevision.value = { revision, graph: parsed.graph }
  } catch { if (token === generation && request === revisionGeneration) revisionError.value = true }
  finally { if (token === generation && request === revisionGeneration) revisionLoading.value = false }
}
function formatRevisionDate(value: string): string {
  return new Date(value).toLocaleString(locale.value, { dateStyle: 'medium', timeStyle: 'short' })
}
function requestRevisionAction(action: 'restore' | 'delete', entry: ProcessHistory['items'][number]): void {
  if (!definition.value || !editable.value || saving.value || archiving.value || deletingRevision.value || revisionDialog || entry.revision === definition.value.revision) return
  const token = generation, expectedRevision = definition.value.revision
  const label = t(action === 'restore' ? 'nativeProcesses.restore' : 'nativeProcesses.deleteRevision')
  const dialog = showConfirmationDialog({
    title: label,
    message: t(action === 'restore' ? 'nativeProcesses.confirmRestore' : 'nativeProcesses.confirmDeleteRevision', { date: formatRevisionDate(entry.created_at) }),
    focus: 'cancel',
    ok: { label, color: action === 'restore' ? 'primary' : 'negative', flat: false },
    cancel: { label: t('common.cancel'), color: 'primary', flat: false, outline: true },
  }).onOk(() => {
    if (token !== generation || !editable.value || definition.value?.revision !== expectedRevision) return
    if (action === 'restore') void restore(entry.revision)
    else void deleteRevision(entry.revision)
  }).onDismiss(() => { if (revisionDialog === dialog) revisionDialog = null })
  revisionDialog = dialog
}
async function deleteRevision(revision: number): Promise<void> {
  if (!definition.value || deletingRevision.value || saving.value) return
  const token = generation
  deletingRevision.value = true
  try {
    await service.deleteRevision(definition.value.code, revision)
    if (token !== generation) return
    if (selectedRevision.value === revision) {
      revisionGeneration++; selectedRevision.value = null; pastRevision.value = null; revisionLoading.value = false; revisionError.value = false
    }
    const { page, rowsPerPage } = historyPagination.value
    const lastPage = Math.max(1, Math.ceil(((history.value?.total ?? 1) - 1) / rowsPerPage))
    await loadHistory(Math.min(page, lastPage), rowsPerPage)
  } catch { if (token === generation) historyError.value = true }
  finally { if (token === generation) deletingRevision.value = false }
}
async function restore(revision: number): Promise<void> {
  if (!definition.value || saving.value) return
  const token = generation
  saving.value = true
  try {
    const next = await service.restore(definition.value.code, revision, definition.value.revision)
    if (token !== generation) return
    apply(next)
    await loadHistory()
  } catch { if (token === generation) historyError.value = true }
  finally { if (token === generation) saving.value = false }
}
function requestArchive(): void {
  if (!definition.value || !editable.value || saving.value || archiving.value || archiveDialog) return
  if (definition.value.archived) { void archive(false); return }
  const token = generation
  const dialog = showConfirmationDialog({
    title: t('nativeProcesses.archive'), message: t('nativeProcesses.confirmArchive'), focus: 'cancel',
    ok: { label: t('nativeProcesses.archive'), color: 'negative', flat: false },
    cancel: { label: t('common.cancel'), color: 'primary', flat: false, outline: true },
  }).onOk(() => { if (token === generation) void archive(true) })
    .onDismiss(() => { if (archiveDialog === dialog) archiveDialog = null })
  archiveDialog = dialog
}
async function archive(archived: boolean): Promise<void> {
  if (!definition.value || !editable.value || saving.value || archiving.value) return
  const token = generation
  archiving.value = true
  try {
    const next = await service.archive(definition.value.code, archived)
    if (token === generation && definition.value) definition.value = { ...definition.value, archived: next.archived }
  } catch (cause) { if (token === generation) report(cause) }
  finally { if (token === generation) archiving.value = false }
}
watch(() => props.code, () => { archiveDialog?.hide(); archiveDialog = null; revisionDialog?.hide(); revisionDialog = null; saving.value = false; archiving.value = false; deletingRevision.value = false; void load() }, { immediate: true })
watch([editable, humanSourceAgentId, loading], () => { clearHumans(); void loadHumans() }, { immediate: true })
onBeforeUnmount(() => { generation++; archiveDialog?.hide(); revisionDialog?.hide(); clearHumans() })
</script>

<style scoped>
.editor-content { display: flex; flex-direction: column; gap: 16px; }
.editor-workspace { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
.editor-diagram { min-width: 0; }
.editor-inspector { padding: 16px; }
.history-workspace { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; align-items: start; }
.history-list { min-width: 0; max-height: 640px; }
.history-list :deep(td.history-revision-cell) { padding: 0; }
.history-list :deep(.q-table__top), .history-list :deep(.q-table__bottom) { flex-shrink: 0; }
.history-list :deep(.q-table__control:has(> .q-table__select) > span) { display: none; }
.history-comparison { min-width: 0; }
.history-revision-selected { background: var(--solaire-blue-light); }
:global(body.body--dark) .history-revision-selected { background: var(--solaire-blue-dark); }
.history-state { min-height: 240px; display: flex; justify-content: center; align-items: center; padding: 24px; text-align: center; }
@media (max-width: 1023.98px) {
  .history-workspace { grid-template-columns: minmax(0, 1fr); }
  .history-list { max-height: 340px; }
}
</style>
