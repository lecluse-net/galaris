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
            <h2 class="text-h6 ellipsis q-ma-none dataset-heading" :title="title || dataset.title">{{ title || dataset.title }}</h2>
          </div>
          <div class="dataset-editor-details row items-center text-caption text-grey-7">
            <q-badge outline color="primary" class="dataset-uri-badge">
              <q-icon name="link" size="13px" class="q-mr-xs" aria-hidden="true" />
              <span class="ellipsis">{{ dataset.uri }}</span>
              <q-tooltip>{{ dataset.uri }}</q-tooltip>
            </q-badge>
            <q-badge outline class="dataset-revision-badge">
              <q-icon name="history" size="13px" class="q-mr-xs" aria-hidden="true" />
              {{ t('datasets.revision') }} {{ dataset.revision }}
            </q-badge>
            <q-btn
              v-if="editable && dataset.can_delete"
              dense
              no-caps
              size="12px"
              padding="0 6px"
              color="negative"
              icon="delete_outline"
              class="dataset-editor-detail-control q-ml-auto"
              :label="t('datasets.deleteDataset')"
              :disable="busy"
              @click="error = ''; confirmDelete = true"
            />
          </div>
        </q-toolbar-title>
        <div class="dataset-editor-actions row items-center q-gutter-xs">
          <q-btn flat round dense icon="refresh" :aria-label="t('datasets.reload')" :disable="busy" @click="reload">
            <q-tooltip>{{ t('datasets.reload') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="editable && dataset.can_write" color="primary" dense no-caps icon="save" :label="t('datasets.save')" :loading="busy" @click="save" />
        </div>
      </q-toolbar>
      <q-separator />
      <q-card-section class="row q-col-gutter-sm dataset-editor-fields q-pa-sm">
        <div class="col-12">
          <q-input v-model="title" outlined dense stack-label hide-bottom-space :label="t('datasets.titleField')" :readonly="busy || !editable || !dataset.can_write" />
        </div>
        <div class="dataset-editor-owner-cell">
          <q-select :model-value="ownerState?.owner" :options="ownerChoices" :option-value="ownerKey" option-label="label"
            class="dataset-editor-owner-field" outlined dense stack-label hide-bottom-space use-input input-debounce="0"
            :label="t('datasets.owner')" :readonly="busy || !editable || !dataset.can_manage || !dataset.can_write || !ownerState?.options.length"
            @filter="filterOwners" @update:model-value="changeOwner">
            <template #selected>
              <div v-if="ownerState?.owner" class="row items-center no-wrap dataset-owner-selected">
                <PersonAvatar :name="ownerState.owner.label" :avatar-url="ownerState.owner.avatar_url" size="22px" />
                <span class="ellipsis q-ml-sm">{{ ownerState.owner.label }}</span>
              </div>
            </template>
            <template #option="scope">
              <q-item v-bind="scope.itemProps">
                <q-item-section avatar><PersonAvatar :name="scope.opt.label" :avatar-url="scope.opt.avatar_url" size="32px" /></q-item-section>
                <q-item-section><q-item-label>{{ scope.opt.label }}</q-item-label><q-item-label caption>{{ t(scope.opt.kind === 'agent' ? 'datasets.ownerAgent' : 'datasets.ownerUser') }}</q-item-label></q-item-section>
              </q-item>
            </template>
          </q-select>
        </div>
        <div class="dataset-editor-sharing-cell">
          <DatasetSharing :key="dataset.id" :id="dataset.id" :lock-version="dataset.lock_version" :editable="!busy && editable && dataset.can_manage" @changed="sharingChanged" />
        </div>
        <div class="col-12">
          <CodeEditor v-model="content" language="json" :label="t('datasets.content')" :readonly="busy || !editable || !dataset.can_write" />
        </div>
      </q-card-section>
      <q-expansion-item :label="t('datasets.usages')" icon="hub" @show="showUsages = true"><DatasetUsages v-if="showUsages" :key="dataset.id" :id="dataset.id" /></q-expansion-item>
      <q-expansion-item :label="t('datasets.history')" icon="history" @show="loadHistory"><q-table v-model:pagination="pagination" :rows="history" :columns="columns" row-key="revision" :rows-per-page-options="[10, 20, 50, 100, 500]" @request="requestHistory"><template #body-cell-revision="slot"><q-td :props="slot"><q-btn flat :label="String(slot.row.revision)" @click="preview(slot.row.revision)" /></q-td></template></q-table></q-expansion-item>
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
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { QTableProps } from 'quasar'
import { CodeEditor, PersonAvatar } from '@/core/util'
import type { Collaborator } from '@/app/share'
import { usePrivilegeStore } from '@/core/authorize'
import { datasetService as service } from '../services/datasetService'
import type { Dataset, DatasetOwnerOptions, DatasetSharing as SharingState } from '../types'
import { formatJson } from '../formatJson'
import DatasetSharing from './DatasetSharing.vue'
import DatasetUsages from './DatasetUsages.vue'
import { errorMessage } from '../errors'
const props = defineProps<{ id: string }>()
const emit = defineEmits<{ loaded: [dataset: Dataset]; updated: [dataset: Dataset]; deleted: [id: string] }>()
const { t } = useI18n(), dataset = shallowRef<Dataset>(), content = ref(''), title = ref(''), error = ref(''), busy = ref(false)
const privileges = usePrivilegeStore(), confirmDelete = ref(false), showUsages = ref(false)
const confirmDiscard = ref(false)
const ownerState = shallowRef<DatasetOwnerOptions>()
const ownerSearch = ref(''), savedContent = ref('')
const ownerChoices = computed(() => (ownerState.value?.options ?? []).filter(option => option.label.toLocaleLowerCase().includes(ownerSearch.value)))
function ownerKey(owner: Collaborator): string { return `${owner.kind}:${owner.id}` }
function filterOwners(search: string, update: (work: () => void) => void): void { update(() => { ownerSearch.value = search.toLocaleLowerCase() }) }
let mounted = true, deleted = false, mutating = false
let pendingDiscard: ((discard: boolean) => void) | undefined
const dirty = computed(() => !!dataset.value && (title.value !== dataset.value.title || content.value !== savedContent.value))
const editable = computed(() => privileges.hasPrivilege('DATASET_EDIT') || privileges.hasPrivilege('DATASET_ADMIN'))
const history = ref<{ revision: number; created_at: string }[]>([]), pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 }), revision = ref(1), historical = ref(''), showRevision = ref(false)
const columns = computed<QTableProps['columns']>(() => [{ name: 'revision', field: 'revision', label: t('datasets.revision'), align: 'left' }, { name: 'created_at', field: 'created_at', label: t('datasets.history'), align: 'left' }])
async function action(work: () => Promise<void>, mutation = false): Promise<void> { if (busy.value) return; busy.value = true; mutating = mutation; error.value = ''; try { await work() } catch (err) { if (mounted) error.value = errorMessage(err, t('datasets.error')) } finally { if (mounted) { busy.value = false; mutating = false } } }
function accept(value: Dataset): void { if (!mounted) return; dataset.value = value; title.value = value.title; content.value = savedContent.value = formatJson(value.content) }
async function load(): Promise<void> { await action(async () => { const value = await service.read(props.id); accept(value); if (mounted) emit('loaded', value); const owners = await service.owner(props.id); if (mounted) ownerState.value = owners }) }
async function reload(): Promise<void> { if (await canLeave()) await load() }
async function save(): Promise<void> { const current = dataset.value; if (!current) return; await action(async () => { JSON.parse(content.value); const source = content.value === savedContent.value ? current.content : content.value; const value = await service.write(current.id, source, current.revision, title.value, current.lock_version); if (mounted) { accept(value); emit('updated', value) } }, true) }
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
async function preview(number: number): Promise<void> { if (dataset.value) await action(async () => { const value = await service.revision(props.id, number); if (mounted) { historical.value = formatJson(value.content); revision.value = number; showRevision.value = true } }) }
async function restore(): Promise<void> { const current = dataset.value; if (!current) return; if (dirty.value && !await canLeave()) return; await action(async () => { const value = await service.restore(current.id, revision.value, current.revision); if (mounted) { accept(value); showRevision.value = false; emit('updated', value) } }, true) }
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
defineExpose({ canLeave })
onBeforeRouteLeave(canLeave)
onBeforeRouteUpdate((to, from) => to.params.id === from.params.id || canLeave())
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void load() })
onBeforeUnmount(() => { mounted = false; window.removeEventListener('beforeunload', beforeUnload); resolveDiscard(false) })
</script>
<style scoped>
.dataset-editor { min-width: 0; }
.dataset-editor-state { min-height: 320px; display: flex; align-items: center; justify-content: center; }
.dataset-editor-toolbar { min-height: 72px; gap: 8px; }
.dataset-editor-icon { color: var(--solaire-blue-accent); flex-shrink: 0; }
.dataset-editor-identity, .dataset-heading, .dataset-editor-fields { min-width: 0; }
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
.dataset-owner-selected { min-width: 0; max-width: 100%; }
.dataset-editor-fields :deep(.q-field--dense .q-field__control) { min-height: 40px; }
.dataset-editor-fields :deep(.q-field--dense .q-field__marginal) { height: 40px; }
@media (max-width: 599.98px) {
  .dataset-editor-toolbar { align-items: flex-start; flex-wrap: wrap; padding-top: 10px; padding-bottom: 10px; }
  .dataset-editor-actions { width: 100%; justify-content: flex-end; }
}
</style>
