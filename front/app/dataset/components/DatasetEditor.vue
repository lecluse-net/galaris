<template>
  <section class="dataset-editor" :aria-label="t('datasets.editor')" :aria-busy="busy">
    <q-banner v-if="error" role="alert">
      {{ error }}
      <template v-if="!dataset" #action><q-btn flat :label="t('datasets.reload')" :disable="busy" @click="load" /></template>
    </q-banner>
    <div v-if="busy && !dataset" class="dataset-editor-state"><q-spinner color="primary" size="36px" /></div>
    <template v-if="dataset">
      <q-toolbar class="dataset-editor-toolbar">
        <q-icon name="data_object" size="40px" class="q-mr-sm dataset-editor-icon" aria-hidden="true" />
        <q-toolbar-title class="dataset-editor-identity">
          <div class="row items-center no-wrap">
            <h2 class="text-h6 q-ma-none dataset-heading" :title="title || dataset.title">{{ title || dataset.title }}</h2>
          </div>
          <div class="dataset-editor-details row items-center text-caption text-grey-7">
            <q-badge outline color="primary" class="dataset-uri-badge dataset-editor-detail-control">
              <q-icon name="link" size="13px" class="q-mr-xs" aria-hidden="true" />
              <span class="ellipsis">{{ dataset.id }}</span>
              <q-tooltip>{{ dataset.uri }}</q-tooltip>
            </q-badge>
            <ResourceTopicBadge :key="dataset.id" :topic-id="dataset.topic_id ?? null"
              kind="dataset" :id="dataset.id" :editable="editable && dataset.can_write && !busy"
              :reassign-topic="changeDatasetTopic" />
            <ResourceSummaryButton :resource-key="dataset.id" :title="dataset.title" :load="loadSummary" />
            <q-badge outline class="dataset-revision-badge">
              <q-icon name="history" size="13px" class="q-mr-xs" aria-hidden="true" />
              {{ t('datasets.revision') }} {{ dataset.revision }}
            </q-badge>
          </div>
        </q-toolbar-title>
        <div class="dataset-editor-actions row items-center q-gutter-xs">
          <q-btn flat round dense icon="refresh" class="dataset-editor-refresh" :aria-label="t('datasets.reload')" :disable="busy" @click="reload">
            <q-tooltip>{{ t('datasets.reload') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="editable && dataset.can_delete" dense color="negative" icon="delete_outline"
            :aria-label="t('datasets.deleteDataset')" :disable="busy"
            @click="error = ''; confirmDelete = true">
            <q-tooltip>{{ t('datasets.deleteDataset') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="editable && dataset.can_write" color="primary" dense no-caps icon="save" :label="t('datasets.save')" :loading="busy" @click="save">
            <q-tooltip>{{ t('datasets.save') }}</q-tooltip>
          </q-btn>
        </div>
      </q-toolbar>
      <q-separator />
      <q-card-section class="row q-col-gutter-sm dataset-editor-fields q-pa-sm">
        <div class="col-12">
          <q-input ref="titleInput" v-model="title" outlined dense stack-label hide-bottom-space :label="t('datasets.titleField')" :readonly="busy || !editable || !dataset.can_write" />
        </div>
        <div class="dataset-editor-owner-cell">
          <OwnerSelect :model-value="ownerState?.owner ? ownerKey(ownerState.owner) : ''" :options="ownerChoices" :current="currentOwner" :current-user-id="ownerState?.current_user_id"
            class="dataset-editor-owner-field" :readonly="busy || !editable || !dataset.can_manage || !dataset.can_write || !ownerChoices.length"
            @update:model-value="selectOwner" @open="refreshOwners" />
        </div>
        <div class="dataset-editor-sharing-cell">
          <DatasetSharing :key="dataset.id" :id="dataset.id" :lock-version="dataset.lock_version" :editable="!busy && editable && dataset.can_manage" @changed="sharingChanged" />
        </div>
      </q-card-section>
      <q-tabs v-model="activeTab" dense no-caps align="left" active-color="primary" class="dataset-editor-tabs">
        <q-tab name="content" :label="t('datasets.contentTab')" />
        <q-tab name="summary" :label="t('datasets.summary')" />
        <q-tab name="history" :label="t('datasets.history')" :disable="busy" />
        <q-tab name="usages" :label="t('datasets.usages')" />
      </q-tabs>
      <q-separator />
      <q-tab-panels v-model="activeTab" keep-alive class="dataset-editor-panels">
        <q-tab-panel name="content" class="dataset-editor-content q-pa-sm">
          <CodeEditor v-model="content" language="json" fill-height :label="t('datasets.content')" :readonly="busy || !editable || !dataset.can_write" />
        </q-tab-panel>
        <q-tab-panel name="summary" class="q-pa-sm">
          <q-input v-model="summary" type="textarea" outlined :label="t('datasets.summary')" :hint="t('datasets.summaryHint')"
            :maxlength="8000" :readonly="busy || !editable || !dataset.can_write" />
          <q-select v-model="keywords" class="q-mt-md" outlined multiple use-input use-chips new-value-mode="add-unique"
            :label="t('datasets.summaryKeywords')" :readonly="busy || !editable || !dataset.can_write" />
        </q-tab-panel>
        <q-tab-panel name="history" class="q-pa-sm">
          <q-table v-model:pagination="pagination" :rows="history" :columns="columns" row-key="revision" :rows-per-page-options="[10, 20, 50, 100, 500]" :loading="busy" @request="requestHistory">
            <template #body-cell-revision="slot"><q-td :props="slot"><q-btn outline :label="String(slot.row.revision)" @click="preview(slot.row.revision)" /></q-td></template>
          </q-table>
        </q-tab-panel>
        <q-tab-panel name="usages" class="q-pa-none">
          <DatasetUsages :key="dataset.id" :id="dataset.id" />
        </q-tab-panel>
      </q-tab-panels>
    </template>
    <q-dialog v-model="showRevision"><q-card style="width: 800px; max-width: 95vw"><q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ t('datasets.revision') }} {{ revision }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('datasets.close')" /></q-card-section><q-card-section><CodeEditor :model-value="historical" language="json" readonly :label="t('datasets.content')" /></q-card-section><q-card-actions align="right"><q-btn v-if="editable && dataset?.can_write" :label="t('datasets.restore')" @click="restore" /></q-card-actions></q-card></q-dialog>
    <q-dialog v-model="confirmDelete"><q-card style="width: 480px; max-width: 95vw"><q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ t('datasets.delete') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('datasets.close')" /></q-card-section><q-card-section><q-banner v-if="error" role="alert">{{ error }}</q-banner>{{ t('datasets.deleteConfirm') }}<p class="q-mt-md">{{ t('datasets.deleteImpact') }}</p></q-card-section><q-card-actions align="right"><q-btn v-close-popup flat :label="t('datasets.cancel')" /><q-btn flat :label="t('datasets.delete')" :loading="busy" @click="remove" /></q-card-actions></q-card></q-dialog>
    <q-dialog :model-value="confirmDiscard" @update:model-value="!$event && resolveDiscard(false)">
      <q-card style="width: 480px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('datasets.unsaved') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('datasets.close')" />
        </q-card-section>
        <q-card-section>{{ t('datasets.discardConfirm') }}</q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="t('datasets.cancel')" />
          <q-btn flat :label="t('datasets.discard')" @click="resolveDiscard(true)" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { QInput, QTableProps } from 'quasar'
import { CodeEditor } from '@/core/util'
import { OwnerSelect, ownerKey, type OwnerOption, type Collaborator } from '@/app/share'
import { usePrivilegeStore } from '@/core/authorize'
import { ResourceTopicBadge, reassignResourceTopic, ResourceSummaryButton, type ResourceSummaryView } from '@/core/util'
import { datasetService as service } from '../services/datasetService'
import type { Dataset, DatasetOwnerOptions, DatasetSharing as SharingState } from '../types'
import { formatJson } from '../formatJson'
import DatasetSharing from './DatasetSharing.vue'
import DatasetUsages from './DatasetUsages.vue'
import { errorMessage } from '../errors'
const props = defineProps<{ id: string }>()
const titleInput = ref<QInput>()
const emit = defineEmits<{ loaded: [dataset: Dataset]; updated: [dataset: Dataset]; deleted: [id: string] }>()
const { t } = useI18n(), dataset = shallowRef<Dataset>(), content = ref(''), title = ref(''), error = ref(''), busy = ref(false)
const privileges = usePrivilegeStore(), confirmDelete = ref(false)
const activeTab = ref('content')
async function loadSummary(signal: AbortSignal): Promise<ResourceSummaryView> {
  const current = dataset.value
  if (!current) return { content: '', mediaType: 'text/plain', keywords: [] }
  const result = await service.read(current.id, signal)
  return { content: result.summary_content ?? '', mediaType: 'text/plain', keywords: result.keywords }
}
const confirmDiscard = ref(false)
const ownerState = shallowRef<DatasetOwnerOptions>()
const savedContent = ref('')
const summary = ref(''), keywords = ref<string[]>([])
const ownerChoices = computed(() => (ownerState.value?.options ?? []).filter((option): option is Collaborator & OwnerOption => option.kind !== 'team'))
const currentOwner = computed(() => { const owner = ownerState.value?.owner; return owner && owner.kind !== 'team' ? owner as OwnerOption : null })
function selectOwner(key: string): void { const owner = ownerChoices.value.find(option => ownerKey(option) === key); if (owner) void changeOwner(owner) }
let mounted = true, deleted = false, mutating = false
let pendingDiscard: ((discard: boolean) => void) | undefined
const dirty = computed(() => !!dataset.value && (title.value !== dataset.value.title || content.value !== savedContent.value
  || summary.value !== (dataset.value.summary_content ?? '') || JSON.stringify(keywords.value) !== JSON.stringify(dataset.value.keywords)))
const editable = computed(() => privileges.hasPrivilege('DATASET_EDIT') || privileges.hasPrivilege('DATASET_ADMIN'))
const history = ref<{ revision: number; created_at: string }[]>([]), pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 }), revision = ref(1), historical = ref(''), showRevision = ref(false)
const columns = computed<QTableProps['columns']>(() => [{ name: 'revision', field: 'revision', label: t('datasets.revision'), align: 'left' }, { name: 'created_at', field: 'created_at', label: t('datasets.history'), align: 'left' }])
async function action(work: () => Promise<void>, mutation = false): Promise<void> { if (busy.value) return; busy.value = true; mutating = mutation; error.value = ''; try { await work() } catch (err) { if (mounted) error.value = errorMessage(err, t('datasets.error')) } finally { if (mounted) { busy.value = false; mutating = false } } }
function accept(value: Dataset): void { if (!mounted) return; dataset.value = value; title.value = value.title; content.value = savedContent.value = formatJson(value.content); summary.value = value.summary_content ?? ''; keywords.value = [...value.keywords] }
async function changeDatasetTopic(topicId: string): Promise<number> {
  const current = dataset.value
  if (!current || busy.value || !editable.value || !current.can_write) throw new Error(t('topic.assignmentAudit.changeError'))
  busy.value = true; mutating = true
  try {
    const result = await reassignResourceTopic('dataset', current.id, topicId, current.topic_id ?? null, current.lock_version)
    if (mounted && dataset.value?.id === current.id) {
      dataset.value = { ...dataset.value, ...result }
      emit('updated', dataset.value)
    }
    return 1
  } finally { if (mounted) { busy.value = false; mutating = false } }
}
async function load(): Promise<void> { await action(async () => { const value = await service.read(props.id); accept(value); if (mounted) emit('loaded', value); const owners = await service.owner(props.id, value.lock_version); if (mounted) ownerState.value = owners }) }
async function refreshOwners(): Promise<void> {
  const current = dataset.value
  if (!current) return
  try {
    const owners = await service.owner(current.id, current.lock_version)
    if (mounted && dataset.value?.id === current.id && dataset.value.lock_version === current.lock_version) ownerState.value = owners
  } catch (err) { if (mounted) error.value = errorMessage(err, t('datasets.error')) }
}
async function reload(): Promise<void> { if (await canLeave()) await load() }
async function save(): Promise<void> {
  const current = dataset.value
  if (!current) return
  await action(async () => {
    JSON.parse(content.value)
    const source = content.value === savedContent.value ? current.content : content.value
    const metadata: { summary_content?: string | null; keywords?: string[] } = {}
    if (summary.value !== (current.summary_content ?? '')) metadata.summary_content = summary.value || null
    if (JSON.stringify(keywords.value) !== JSON.stringify(current.keywords)) metadata.keywords = [...keywords.value]
    const value = await service.write(current.id, source, current.revision, title.value, current.lock_version, metadata)
    if (mounted) { accept(value); emit('updated', value) }
  }, true)
}
async function changeOwner(owner: Collaborator): Promise<void> {
  const current = dataset.value
  const owners = ownerState.value
  if (!current || !owners || !editable.value || !current.can_manage || !current.can_write || owner.kind === 'team') return
  if (owners.owner && ownerKey(owner) === ownerKey(owners.owner)) return
  const kind = owner.kind
  await action(async () => {
    const value = await service.transferOwner(current.id, kind, owner.id, current.lock_version)
    if (!mounted) return
    dataset.value = value
    ownerState.value = { ...owners, owner }
    emit('updated', value)
  }, true)
}
function sharingChanged(state: SharingState): void { if (dataset.value) dataset.value = { ...dataset.value, lock_version: state.lock_version, can_manage: state.can_manage } }
async function remove(): Promise<void> { const current = dataset.value; if (!current?.can_delete || !editable.value) return; await action(async () => { await service.remove(current.id, current.lock_version); if (mounted) { deleted = true; confirmDelete.value = false; emit('deleted', current.id) } }, true) }
async function loadHistory(): Promise<void> { if (dataset.value) await action(async () => { const page = await service.history(props.id, pagination.value.page, pagination.value.rowsPerPage); if (mounted) { history.value = page.items; pagination.value.rowsNumber = page.total } }) }
function requestHistory({ pagination: value }: { pagination: { page: number; rowsPerPage: number } }): void { Object.assign(pagination.value, value); void loadHistory() }
watch(activeTab, tab => { if (tab === 'history') void loadHistory() })
async function preview(number: number): Promise<void> { if (dataset.value) await action(async () => { const value = await service.revision(props.id, number); if (mounted) { historical.value = formatJson(value.content); revision.value = number; showRevision.value = true } }) }
async function restore(): Promise<void> { const current = dataset.value; if (!current) return; if (dirty.value && !await canLeave()) return; await action(async () => { const value = await service.restore(current.id, revision.value, current.revision); if (mounted) { accept(value); showRevision.value = false; activeTab.value = 'content'; emit('updated', value) } }, true) }
function resolveDiscard(discard: boolean): void { const resolve = pendingDiscard; pendingDiscard = undefined; confirmDiscard.value = false; resolve?.(discard) }
function canLeave(): boolean | Promise<boolean> {
  if (deleted) return true
  if (mutating) return false
  if (!dirty.value) return true
  if (pendingDiscard) return false
  confirmDiscard.value = true
  return new Promise(resolve => { pendingDiscard = resolve })
}
function beforeUnload(event: BeforeUnloadEvent): void { if (dirty.value && !deleted) { event.preventDefault(); event.returnValue = '' } }
function requestRowAction(action: 'rename' | 'delete'): void {
  if (!editable.value || !dataset.value?.can_write) return
  if (action === 'delete') { if (dataset.value.can_delete) confirmDelete.value = true }
  else { titleInput.value?.focus(); titleInput.value?.select() }
}
defineExpose({ canLeave, requestRowAction })
onBeforeRouteLeave(canLeave)
onBeforeRouteUpdate((to, from) => to.params.id === from.params.id || canLeave())
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load() })
onBeforeUnmount(() => { mounted = false; window.removeEventListener('beforeunload', beforeUnload); resolveDiscard(false) })
</script>
<style scoped>
.dataset-editor { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; }
.dataset-editor > :not(.dataset-editor-panels) { flex-shrink: 0; }
.dataset-editor-panels { flex: 1; min-height: 180px; background: transparent; }
.dataset-editor-content { display: flex; flex-direction: column; }
.dataset-editor-state { min-height: 320px; display: flex; align-items: center; justify-content: center; }
.dataset-editor-toolbar { min-height: 72px; gap: 8px; }
.dataset-editor-icon { color: var(--solaire-blue-accent); flex-shrink: 0; }
.dataset-editor-identity, .dataset-heading, .dataset-editor-fields { min-width: 0; }
.dataset-heading { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dataset-editor-details { gap: 4px; margin-top: 4px; }
.dataset-editor-detail-control { height: 24px; min-height: 24px; }
.dataset-uri-badge { max-width: min(100%, 360px); padding: 4px 7px; font-weight: 400; }
.dataset-revision-badge { padding: 4px 7px; font-weight: 400; color: var(--solaire-gray-accent); }
.dataset-editor-actions { flex: 0 0 auto; }
.dataset-editor-owner-cell { display: flex; width: 40%; min-width: 0; }
.dataset-editor-sharing-cell { width: 60%; min-width: 0; }
.dataset-editor-owner-field { flex: 1; min-width: 0; }
.dataset-editor-owner-field :deep(.q-field__inner),
.dataset-editor-owner-field :deep(.q-field__control) { height: 100%; }
.dataset-editor-owner-field :deep(.q-field__native) { flex-wrap: nowrap; }
.dataset-editor-fields :deep(.q-field--dense .q-field__control) { min-height: 40px; }
.dataset-editor-fields :deep(.q-field--dense .q-field__marginal) { height: 40px; }
@media (max-width: 1023.98px) {
  .dataset-editor-toolbar { display: grid; grid-template-columns: 40px minmax(0, 1fr); align-items: start; padding: 10px 8px; }
  .dataset-editor-icon { margin-right: 0; }
  .dataset-editor-identity { padding: 0; white-space: normal; }
  .dataset-heading { white-space: normal; overflow-wrap: anywhere; }
  .dataset-editor-details { flex-wrap: wrap; }
  .dataset-uri-badge { max-width: 100%; }
  .dataset-editor-actions { grid-column: 1 / -1; flex-wrap: wrap; justify-content: flex-end; margin-left: 0; }
  .dataset-editor-refresh { margin-right: auto; }
}
</style>
