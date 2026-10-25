<template>
  <q-page class="q-pa-md">
    <PageHeader icon="science" :title="t('processLab.title')" :description="t('processLab.description')" />
    <div class="q-gutter-y-md">
      <q-banner v-if="error" role="alert">{{ error }}</q-banner>
      <template v-if="canEdit">
        <q-input v-model="agentId" type="number" outlined :label="t('nativeProcesses.agent')" />
        <q-input v-model="code" outlined :label="t('nativeProcesses.code')" />
        <q-input v-model="title" outlined :label="t('nativeProcesses.titleField')" />
        <CodeEditor v-model="cases" language="json" :label="t('processLab.cases')" />
        <q-btn outline :loading="busy" :label="t('processLab.createDataset')" @click="saveDataset" />
        <q-expansion-item icon="auto_awesome" :label="t('processLab.generate')">
          <q-input v-model="instructions" outlined type="textarea" :label="t('processLab.instructions')" />
          <q-input v-model.number="count" outlined type="number" min="1" max="20" :label="t('processLab.count')" />
          <q-btn outline :label="t('processLab.generate')" :loading="busy" @click="generate" />
        </q-expansion-item>
        <q-input v-model="dataset" outlined :label="t('processLab.dataset')" />
        <q-banner>{{ t('processLab.notice') }}</q-banner>
        <q-btn color="primary" icon="play_arrow" :label="t('processLab.start')" :loading="busy" @click="start" />
      </template>
      <div class="row q-col-gutter-sm"><q-input v-model="campaignId" class="col" outlined :label="t('processLab.campaignId')" /><q-btn flat icon="search" :label="t('processLab.open')" @click="open" /></div>
      <template v-if="campaign">
        <div class="row items-center"><div class="text-h6">{{ campaign.title }}</div><q-badge class="q-ml-md">{{ campaign.status }}</q-badge><q-space />
          <q-btn v-if="canEdit && !terminal" outline icon="stop" :label="t('nativeProcesses.cancel')" @click="cancel" /></div>
        <q-table :rows="campaign.items" :columns="columns" row-key="id" v-model:pagination="pagination" :rows-per-page-options="[10, 20, 50, 100, 500]" @request="request">
          <template #body-cell-run="scope"><q-td :props="scope"><q-btn v-if="scope.row.run_id" flat :label="scope.row.run_id" :to="`/process/internal/run/${scope.row.run_id}`" /></q-td></template>
          <template #body-cell-evidence="scope"><q-td :props="scope"><q-btn flat icon="visibility" :label="t('processLab.evidence')" @click="selected = scope.row.evidence" /></q-td></template>
        </q-table>
        <CodeEditor v-if="selected" :model-value="JSON.stringify(selected, null, 2)" language="json" readonly :label="t('processLab.evidence')" />
      </template>
    </div>
  </q-page>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableColumn } from 'quasar'
import { usePrivilegeStore } from '@/core/authorize'
import { CodeEditor, PageHeader } from '@/core/util'
import { processCampaignService as service, type ProcessCampaign, type SyntheticCase } from '../services/processCampaignService'
const { t } = useI18n(), privileges = usePrivilegeStore()
const code = ref(''), title = ref(''), agentId = ref<string | number>(''), cases = ref('[{"input":{},"expected":null}]'), dataset = ref(''), count = ref(8), instructions = ref('')
const busy = ref(false), error = ref(''), campaignId = ref(''), campaign = ref<ProcessCampaign | null>(null), selected = ref<Record<string, unknown> | null>(null)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0, timer: ReturnType<typeof setTimeout> | undefined
let alive = true
const commands = new Map<string, { signature: string; key: string }>()
const canEdit = computed(() => privileges.hasPrivilege('PROCESS_EVALUATION_EDIT'))
const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(campaign.value?.status ?? ''))
const columns = computed<QTableColumn[]>(() => [
  { name: 'position', label: t('nativeProcesses.occurrences'), field: 'position', align: 'left' },
  { name: 'status', label: t('processes.status'), field: 'status', align: 'left' },
  { name: 'run', label: t('nativeProcesses.runId'), field: 'run_id', align: 'left' },
  { name: 'evidence', label: t('processLab.evidence'), field: 'evidence', align: 'left' },
])
function report(cause: unknown): void { const data = cause as { response?: { data?: { detail?: string } } }; error.value = data.response?.data?.detail ?? (cause instanceof Error ? cause.message : t('nativeProcesses.error')) }
async function action(work: () => Promise<void>): Promise<void> { if (busy.value) return; busy.value = true; error.value = ''; try { await work() } catch (cause) { if (alive) report(cause) } finally { if (alive) busy.value = false } }
function identity(kind: string): { agent_id: number; title: string; invocation_key: string } { const signature = JSON.stringify([agentId.value, title.value, code.value, dataset.value, cases.value, instructions.value, count.value]); const prior = commands.get(kind); const value = prior?.signature === signature ? prior : { signature, key: crypto.randomUUID() }; commands.set(kind, value); return { agent_id: Number(agentId.value), title: title.value, invocation_key: value.key } }
async function saveDataset(): Promise<void> { await action(async () => { const parsed: unknown = JSON.parse(cases.value); if (!Array.isArray(parsed)) throw new Error(t('processes.invalidJson')); const value = await service.dataset({ ...identity('dataset'), cases: parsed as SyntheticCase[] }); if (alive) { dataset.value = value.dataset_uri; commands.delete('dataset') } }) }
async function generate(): Promise<void> { await action(async () => { const value = await service.generate({ ...identity('generate'), code: code.value, instructions: instructions.value, count: count.value }); if (alive) { dataset.value = value.dataset_uri; commands.delete('generate') } }) }
async function start(): Promise<void> { await action(async () => { const result = await service.start({ ...identity('campaign'), code: code.value, dataset_id: dataset.value.replace(/^data:\/\//, '') }); if (!alive) return; commands.delete('campaign'); campaignId.value = result.id; await open() }) }
async function open(): Promise<void> { const token = ++generation, id = campaignId.value; clearTimeout(timer); if (campaign.value?.id !== id) { selected.value = null; campaign.value = null }
  try { const next = await service.get(id, pagination.value.page, pagination.value.rowsPerPage); if (token !== generation) return; campaign.value = next; pagination.value.rowsNumber = next.total; if (!terminal.value) timer = setTimeout(() => void open(), 2000) }
  catch (cause) { if (token === generation) report(cause) }
}
async function cancel(): Promise<void> { if (campaign.value) await action(async () => { await service.cancel(campaign.value!.id); await open() }) }
function request(value: { pagination: { page: number; rowsPerPage: number } }): void { pagination.value = { ...pagination.value, ...value.pagination }; void open() }
onBeforeUnmount(() => { alive = false; generation++; clearTimeout(timer) })
</script>
