<template>
  <q-dialog v-model="open" allow-focus-outside no-route-dismiss :maximized="$q.screen.lt.md" @before-hide="beforeHide">
    <q-card class="document-navigation-dialog galaris-detail-dialog galaris-dialog-card" :class="cardClass">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <DocumentNavigationButtons class="q-mr-sm" :can-go-back="!busy && history.canGoBack.value" :can-go-forward="!busy && history.canGoForward.value" @back="navigateHistory(-1)" @forward="navigateHistory(1)" />
        <DocumentIcon v-if="current" :document-id="current.id" :title="currentTitle" size="24px" class="q-mr-sm" />
        <div class="text-h6 ellipsis">{{ currentTitle }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <div class="document-navigation-dialog-body galaris-dialog-body">
        <q-linear-progress v-if="busy" indeterminate color="primary" />
        <q-banner v-if="loadError" role="alert">
          {{ t('documents.loadError') }}
          <template #action><q-btn outline :label="t('common.retry')" @click="retry" /></template>
        </q-banner>
        <DocumentEditor v-if="current" :key="`${currentAgentId}:${current.id}`" ref="editor"
          :document-id="current.id" :agent-id="currentAgentId" :initial-document="current" :editable="editable"
          content-min-height="min(42vh, 440px)" content-max-height="52vh"
          @loaded="onLoaded" @updated="onUpdated" @unavailable="emit('unavailable', $event)" @deleted="onDeleted" />
      </div>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, provide, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { documentNavigationKey, DocumentNavigationButtons, useDocumentHistory } from '@/core/util'
import { DatasetDocumentRedirect, memoryService } from '../services/memoryService'
import type { MemoryItemDetail } from '../types'
import DocumentEditor from './DocumentEditor.vue'
import DocumentIcon from './DocumentIcon.vue'

const open = defineModel<boolean>({ required: true })
const { documentId, agentId, title = '', editable = false, cardClass = '' } = defineProps<{
  documentId: string | null; agentId: number | null; title?: string; editable?: boolean; cardClass?: string
}>()
const emit = defineEmits<{
  loaded: [document: MemoryItemDetail]; updated: [document: MemoryItemDetail]
  unavailable: [id: string]; deleted: [id: string]
}>()
const { t } = useI18n(), $q = useQuasar()
const router = useRouter()
const history = useDocumentHistory({
  active: () => open.value,
  leave: async () => {
    if (!await flush()) return false
    open.value = false
    return true
  },
  navigate: async (id, position) => {
    await selectDocument(id, position)
    return current.value?.id === id
  },
})
const editor = useTemplateRef<InstanceType<typeof DocumentEditor>>('editor')
const current = shallowRef<MemoryItemDetail | null>(null)
const currentAgentId = ref<number | null>(null)
const currentTitle = computed(() => current.value?.title || title || t('nav.documents'))
const busy = ref(false)
const loadError = ref(false)
let generation = 0
let disposed = false

async function flush(): Promise<boolean> { return await editor.value?.flush() ?? true }
async function selectDocument(id: string, position?: number, initial = false): Promise<void> {
  const selection = ++generation
  busy.value = true
  loadError.value = false
  try {
    if (!await flush()) {
      if (selection === generation) $q.notify({ type: 'negative', message: t('documents.autosaveError') })
      return
    }
    if (disposed || !open.value || selection !== generation) return
    const detail = agentId !== null && (initial || id === documentId)
      ? { item: await memoryService.getDocument(id, agentId), agent_id: agentId }
      : await memoryService.getManagedDocument(id)
    if (disposed || !open.value || selection !== generation) return
    // The current document remains editable while the destination is loading.
    if (!await flush()) {
      if (selection === generation) $q.notify({ type: 'negative', message: t('documents.autosaveError') })
      return
    }
    if (disposed || !open.value || selection !== generation) return
    current.value = detail.item
    currentAgentId.value = detail.agent_id
    if (initial) history.reset()
    history.record(id, position)
  } catch (error) {
    if (disposed || !open.value || selection !== generation) return
    if (error instanceof DatasetDocumentRedirect) {
      open.value = false
      await router.push(error.href)
      return
    }
    if (!current.value) { loadError.value = true; emit('unavailable', id) }
    else $q.notify({ type: 'negative', message: t('documents.loadError') })
  } finally {
    if (selection === generation) busy.value = false
  }
}
async function navigateHistory(direction: -1 | 1): Promise<void> {
  if (busy.value) return
  const target = history.target(direction)
  if (target) await history.go(direction)
}
provide(documentNavigationKey, async id => {
  if (current.value?.id !== id) await selectDocument(id)
})
function onLoaded(document: MemoryItemDetail): void { current.value = document; emit('loaded', document) }
function onUpdated(document: MemoryItemDetail): void { current.value = document; emit('updated', document) }
function onDeleted(id: string): void { history.forget(id); emit('deleted', id); open.value = false }
function retry(): void { if (documentId) void selectDocument(documentId, undefined, true) }
function beforeHide(): void { ++generation; busy.value = false; void flush() }
watch([open, () => documentId, () => agentId], ([visible, id], previous) => {
  ++generation
  if (!visible) return
  if (!previous?.[0]) current.value = null
  if (id) void selectDocument(id, undefined, true)
}, { immediate: true })
watch(() => router.currentRoute.value.fullPath, () => { open.value = false })
onBeforeUnmount(() => { disposed = true; ++generation })
defineExpose({ flush })
</script>

<style scoped>
.document-navigation-dialog { display: flex; width: min(94vw, 980px); max-width: 980px; min-height: 420px; max-height: calc(100dvh - 32px); flex-direction: column; }
.document-navigation-dialog-body { min-height: 0; flex: 1 1 auto; overflow-y: auto; }
</style>
