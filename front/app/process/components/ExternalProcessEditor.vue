<template>
  <div>
    <PageHeader :icon="navigationIcon('account_tree')" :title="definitionForm.label || t('processes.importExternal')" />
    <div class="row items-center q-gutter-sm q-mb-md">
      <q-btn color="warning" icon="arrow_back" :label="t('processes.backToList')" to="/process" />
      <q-space />
      <q-btn v-if="canAdmin && !loading && !loadError" color="primary" icon="save" :label="t('processes.save')"
        :loading="saving" :disable="!id && (!definitionForm.tool_id || !definitionForm.engine_process_id || !definitionForm.label)" @click="saveDefinition" />
      <q-btn v-if="id && canAdmin && !loading && !loadError" color="negative" icon="delete" :label="t('processes.delete')" :disable="saving" @click="removeDefinition" />
    </div>
    <div v-if="loading" class="flex flex-center q-pa-lg"><q-spinner color="primary" size="2.5em" /></div>
    <q-banner v-else-if="loadError" role="alert">
      {{ t('processes.genericError') }}
      <template #action><q-btn outline :label="t('nativeProcesses.retry')" @click="load" /></template>
    </q-banner>
    <q-banner v-else-if="!id && !canAdmin">{{ t('nativeProcesses.readOnly') }}</q-banner>
    <q-card v-else flat bordered class="q-pa-md">
      <q-form class="q-gutter-md" @submit.prevent="saveDefinition">
        <template v-if="!id">
          <q-banner dense rounded>
            <template #avatar><q-icon name="lock_open" /></template>
            {{ t('processes.creationNotice') }}
          </q-banner>
          <q-select
            v-model="definitionForm.tool_id"
            :options="toolOptions"
            emit-value
            map-options
            dense
            outlined
            :label="t('processes.tool')"
            @update:model-value="onToolChanged"
          />
          <div v-if="selectedToolCode === 'n8n'" class="process-workflow-select-row">
            <q-select
              :model-value="definitionForm.engine_process_id"
              class="col"
              :options="workflowOptions"
              emit-value
              map-options
              dense
              outlined
              :label="t('processes.workflow')"
              :hint="t('processes.workflowHint')"
              @update:model-value="onWorkflowChanged"
            >
              <template #option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>{{ scope.opt.label }}</q-item-label>
                    <q-item-label caption>{{ scope.opt.value }}</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-icon v-if="scope.opt.disable" name="block" color="negative" />
                  </q-item-section>
                </q-item>
              </template>
              <template #no-option><q-item><q-item-section class="text-grey">{{ t('processes.noWorkflow') }}</q-item-section></q-item></template>
            </q-select>
            <q-btn v-if="canAdmin" class="process-workflow-sync" outline round color="secondary" icon="sync" :aria-label="t('processes.syncN8n')" @click="syncSelectedTool" />
          </div>
          <AgentSelect v-model="definitionForm.agent_id" :options="agentOptions" clearable dense outlined :label="t('processes.agent')" />
        </template>

        <q-card v-else flat bordered>
          <q-card-section class="q-py-sm">
            <div class="process-metadata">
              <div class="process-metadata-item">
                <q-avatar size="32px" color="grey-3" text-color="grey-7"><q-icon name="extension" size="20px" /></q-avatar>
                <div><div class="metadata-label">{{ t('processes.tool') }}</div><div class="text-weight-bold">{{ toolLabel(definitionForm.tool_id) }}</div></div>
              </div>
              <div class="process-metadata-item">
                <AgentAvatar v-if="definitionForm.agent_id !== null" :agent-id="definitionForm.agent_id" :name="agentLabel(definitionForm.agent_id)" :has-avatar="agentHasAvatar(definitionForm.agent_id)" size="32px" />
                <q-avatar v-else size="32px" color="grey-3" text-color="grey-7"><q-icon name="person" size="20px" /></q-avatar>
                <div><div class="metadata-label">{{ t('processes.agent') }}</div><div class="text-weight-bold">{{ agentLabel(definitionForm.agent_id) }}</div></div>
              </div>
              <div class="process-metadata-item">
                <q-avatar size="32px" color="grey-3" text-color="grey-7"><q-icon name="fingerprint" size="20px" /></q-avatar>
                <div><div class="metadata-label">{{ t('processes.engineProcessId') }}</div><div class="text-weight-bold">{{ definitionForm.engine_process_id }}</div></div>
              </div>
            </div>
          </q-card-section>
        </q-card>

        <q-input v-model="definitionForm.description" outlined type="textarea" autogrow :readonly="!canAdmin" :label="t('processes.description')" />

      </q-form>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { AgentAvatar, AgentSelect } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader, showConfirmationDialog } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { processService, type AgentOption, type ProcessTool, type ToolProcessDefinition } from '../services/processService'

const props = defineProps<{ id?: number }>()
const { t } = useI18n(), $q = useQuasar(), router = useRouter(), privilegeStore = usePrivilegeStore()
const canAdmin = computed(() => privilegeStore.hasPrivilege(privileges.PROCESS_ADMIN))
const loading = ref(false), loadError = ref(false), saving = ref(false)
const processTools = ref<ProcessTool[]>([]), agents = ref<AgentOption[]>([]), discovered = ref<ToolProcessDefinition[]>([])
const definitionForm = reactive({ agent_id: null as number | null, tool_id: null as number | null, engine_process_id: '', label: '', description: null as string | null })
const toolOptions = computed(() => processTools.value.map(tool => ({ label: tool.label, value: tool.id })))
const selectedToolCode = computed(() => processTools.value.find(tool => tool.id === definitionForm.tool_id)?.code ?? '')
const workflowOptions = computed(() => discovered.value.map(workflow => ({ label: workflow.label, value: workflow.engine_process_id, disable: !workflow.active })))
const agentOptions = computed(() => agents.value.map(agent => ({ label: agent.label, value: agent.id })))
let generation = 0
let confirmation: ReturnType<typeof showConfirmationDialog> | null = null

function agentLabel(agentId: number | null): string { return agents.value.find(agent => agent.id === agentId)?.label ?? '—' }
function agentHasAvatar(agentId: number): boolean { return agents.value.some(agent => agent.id === agentId && agent.has_avatar) }
function toolLabel(toolId: number | null): string { return processTools.value.find(tool => tool.id === toolId)?.label ?? '—' }
function onWorkflowChanged(engineProcessId: string): void {
  const workflow = discovered.value.find(item => item.engine_process_id === engineProcessId)
  if (workflow) Object.assign(definitionForm, { engine_process_id: workflow.engine_process_id, label: workflow.label, description: workflow.description })
}
function onToolChanged(): void { Object.assign(definitionForm, { engine_process_id: '', label: '', description: null }); discovered.value = [] }
function notifyError(error: unknown): void {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  $q.notify({ type: 'negative', message: typeof detail === 'string' ? detail : t('processes.genericError') })
}
async function syncSelectedTool(): Promise<void> {
  if (!canAdmin.value || !selectedToolCode.value) return
  const token = generation, toolCode = selectedToolCode.value
  try {
    const workflows = await processService.syncDefinitions(toolCode)
    if (token === generation && toolCode === selectedToolCode.value) discovered.value = workflows
  } catch (error) { if (token === generation) notifyError(error) }
}
async function load(): Promise<void> {
  const token = ++generation
  confirmation?.hide(); confirmation = null
  loading.value = true; loadError.value = false; saving.value = false; discovered.value = []
  Object.assign(definitionForm, { agent_id: null, tool_id: null, engine_process_id: '', label: '', description: null })
  try {
    if (props.id !== undefined && (!Number.isSafeInteger(props.id) || props.id <= 0)) throw new Error('Invalid process identifier')
    const [tools, options, definition] = await Promise.all([
      processService.tools(), processService.agents(), props.id === undefined ? null : processService.definition(props.id),
    ])
    if (token !== generation) return
    processTools.value = tools; agents.value = options
    if (definition) Object.assign(definitionForm, { agent_id: definition.agent_id, tool_id: definition.tool_id, engine_process_id: definition.engine_process_id, label: definition.label, description: definition.description })
    else definitionForm.tool_id = tools.find(tool => tool.code === 'n8n')?.id ?? tools[0]?.id ?? null
  } catch { if (token === generation) loadError.value = true }
  finally { if (token === generation) loading.value = false }
}
async function saveDefinition(): Promise<void> {
  if (!canAdmin.value || saving.value || loading.value || loadError.value || !definitionForm.tool_id) return
  if (props.id === undefined && (!definitionForm.engine_process_id || !definitionForm.label)) return
  const token = generation, id = props.id
  saving.value = true
  try {
    const record = id === undefined
      ? await processService.createDefinition({ ...definitionForm, tool_id: definitionForm.tool_id })
      : await processService.updateDefinition(id, { description: definitionForm.description })
    if (token !== generation) return
    definitionForm.description = record.description
    $q.notify({ type: 'positive', message: t('processes.saved') })
    if (id === undefined) await router.replace(`/process/external/${record.id}`)
  } catch (error) { if (token === generation) notifyError(error) }
  finally { if (token === generation) saving.value = false }
}
function removeDefinition(): void {
  if (!canAdmin.value || props.id === undefined || saving.value) return
  const id = props.id, token = generation
  confirmation?.hide()
  confirmation = showConfirmationDialog({ title: t('common.confirm'), message: t('processes.confirmDelete'), cancel: true }).onOk(async () => {
    if (!canAdmin.value || token !== generation) return
    saving.value = true
    try {
      await processService.deleteDefinition(id)
      if (token !== generation) return
      $q.notify({ type: 'positive', message: t('processes.deleted') })
      await router.push('/process')
    } catch (error) { if (token === generation) notifyError(error) }
    finally { if (token === generation) saving.value = false }
  })
}
watch(() => props.id, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { generation++; confirmation?.hide() })
</script>

<style scoped>
.process-workflow-select-row { display: flex; align-items: flex-start; gap: 8px; }
.process-workflow-select-row .q-select { flex: 1 1 auto; min-width: 0; }
.process-workflow-sync { margin-top: 4px; }
.process-metadata { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.process-metadata-item { display: flex; align-items: center; gap: 8px; min-width: 0; overflow-wrap: anywhere; }
.metadata-label { font-size: 12px; line-height: 1.2; }
@media (max-width: 599px) {
  .process-workflow-select-row { flex-wrap: wrap; }
  .process-metadata { grid-template-columns: 1fr; }
}
</style>
