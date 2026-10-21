<template>
  <q-page class="datasets-page q-pa-md" :class="{ 'viewport-page--desktop': !$q.screen.lt.md }" :style-fn="pageStyle">
    <PageHeader icon="data_object" :title="t('datasets.title')" :description="t('datasets.description')" />
    <q-card flat bordered class="datasets-workspace">
      <q-splitter v-model="splitter" :limits="[20, 55]" :disable="$q.screen.lt.md" class="datasets-splitter"
        :class="{ 'datasets-splitter--selected': selectedId }">
        <template #before>
          <DatasetLibraryNavigation ref="navigation" :selected-id="selectedId" @create="openCreate" @action="rowAction" />
        </template>
        <template #separator>
          <span class="dataset-splitter-handle" role="separator" tabindex="0" aria-orientation="vertical"
            :aria-label="t('datasets.resizeList')" :aria-valuenow="splitter" :aria-valuemin="20" :aria-valuemax="55"
            @keydown="resizeList">
            <q-icon name="drag_indicator" size="16px" aria-hidden="true" />
          </span>
        </template>
        <template #after>
          <template v-if="selectedId">
            <DatasetEditor :key="selectedId" ref="editor" :id="selectedId" @loaded="editorLoaded" @updated="refresh" @deleted="removed" />
          </template>
          <div v-else class="dataset-placeholder text-grey-7">
            <q-icon name="data_object" size="48px" aria-hidden="true" />
            <div>{{ t('datasets.selectDataset') }}</div>
          </div>
        </template>
      </q-splitter>
    </q-card>
    <q-dialog v-model="creating">
      <q-card style="width: 480px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('datasets.new') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('datasets.close')" />
        </q-card-section>
        <q-card-section>
          <q-banner v-if="createError" role="alert" class="q-mb-md">{{ createError }}</q-banner>
          <q-input v-model="title" outlined autofocus :label="t('datasets.titleField')" :disable="creatingBusy" @keyup.enter="create" />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline :label="t('datasets.cancel')" />
          <q-btn color="primary" :disable="!title.trim()" :loading="creatingBusy" :label="t('datasets.new')" @click="create" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { PageHeader } from '@/core/util'
import DatasetEditor from '../components/DatasetEditor.vue'
import DatasetLibraryNavigation from '../components/DatasetLibraryNavigation.vue'
import { datasetService } from '../services/datasetService'
import type { Dataset } from '../types'
const { t } = useI18n(), route = useRoute(), router = useRouter(), $q = useQuasar()
const selectedId = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const splitter = ref(30), title = ref(''), creating = ref(false), creatingBusy = ref(false), createError = ref('')
const navigation = useTemplateRef<InstanceType<typeof DatasetLibraryNavigation>>('navigation')
const editor = useTemplateRef<InstanceType<typeof DatasetEditor>>('editor')
let mounted = true, createFolderId: string | undefined, pendingAction: { id: string; action: 'rename' | 'delete' } | null = null
function pageStyle(offset: number, height: number): { height: string } { return { height: `${height - offset}px` } }
function refresh(): void { void navigation.value?.refresh() }
function openCreate(folderId?: string): void { createFolderId = folderId; createError.value = ''; title.value = ''; creating.value = true }
function resizeList(event: KeyboardEvent): void {
  const values: Record<string, number> = { ArrowLeft: splitter.value - 2, ArrowRight: splitter.value + 2, Home: 20, End: 55 }
  const value = values[event.key]
  if (value === undefined) return
  event.preventDefault(); splitter.value = Math.min(55, Math.max(20, value))
}
async function rowAction(item: Dataset, action: 'rename' | 'delete'): Promise<void> {
  if (selectedId.value === item.id) { editor.value?.requestRowAction(action); return }
  const pending = { id: item.id, action }
  pendingAction = pending
  const failure = await router.push('/dataset/' + item.id)
  if (failure && pendingAction === pending) pendingAction = null
}
async function editorLoaded(item: Dataset): Promise<void> {
  if (pendingAction?.id !== item.id) return
  const action = pendingAction.action; pendingAction = null
  await nextTick(); if (selectedId.value === item.id) editor.value?.requestRowAction(action)
}
async function create(): Promise<void> {
  if (!title.value.trim() || creatingBusy.value) return
  creatingBusy.value = true; createError.value = ''
  const path = route.fullPath, folderId = createFolderId
  try {
    const item = await datasetService.create(title.value.trim())
    if (folderId) {
      try { await datasetService.move({ kind: 'dataset', identity: item.id, parent_id: folderId }) }
      catch { if (mounted) $q.notify({ type: 'warning', message: t('datasets.library.error') }) }
    }
    if (!mounted) return
    creating.value = false; title.value = ''; refresh()
    if (route.fullPath === path) await router.push('/dataset/' + item.id)
  } catch { if (mounted) createError.value = t('datasets.error') }
  finally { if (mounted) creatingBusy.value = false }
}
async function removed(id: string): Promise<void> { refresh(); if (selectedId.value === id) await router.push('/dataset') }
onBeforeUnmount(() => { mounted = false })
</script>
<style scoped>
.datasets-page { display: flex; flex-direction: column; overflow: hidden; padding-bottom: 0; }
.datasets-page > :not(.datasets-workspace) { flex-shrink: 0; }
.datasets-workspace { flex: 1; min-height: 0; overflow: hidden; }
.datasets-splitter { height: 100%; min-height: 0; }
.datasets-splitter :deep(> .q-splitter__after) { overflow: auto; }
.datasets-splitter :deep(> .q-splitter__separator) { background: color-mix(in srgb, var(--q-dark) 10%, transparent); }
.dataset-splitter-handle { display: flex; width: 20px; height: 42px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 10px; color: var(--solaire-gray-accent); background: var(--q-card-background, #fff); box-shadow: 0 2px 8px rgba(35, 46, 66, .12); }
.dataset-splitter-handle:hover, .dataset-splitter-handle:focus-visible { color: var(--solaire-blue-accent); }
.dataset-splitter-handle:focus-visible { outline: 2px solid var(--solaire-blue-accent); }
:global(body.body--dark) .dataset-splitter-handle { background: var(--q-dark-page); box-shadow: 0 2px 8px rgba(0, 0, 0, .38); }
.dataset-placeholder { height: 100%; min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; padding: 16px; }
@media (min-width: 1024px) {
  .datasets-splitter :deep(> .q-splitter__before),
  .datasets-splitter :deep(> .q-splitter__after) { min-height: 0; }
}
@media (max-width: 1023.98px) {
  .datasets-splitter :deep(> .q-splitter__before) { width: 100% !important; }
  .datasets-splitter :deep(> .q-splitter__separator),
  .datasets-splitter :deep(> .q-splitter__after) { display: none; }
  .datasets-splitter--selected :deep(> .q-splitter__before) { display: none; }
  .datasets-splitter--selected :deep(> .q-splitter__after) { display: block; width: 100% !important; }
}
</style>
