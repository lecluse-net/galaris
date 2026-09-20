<template>
  <div class="memory-history">
    <aside class="column no-wrap">
      <q-select :model-value="pageSize" :options="pageSizeOptions" dense outlined behavior="menu"
        :label="t('memory.historyPageSize')" :disable="loading" class="q-mb-sm"
        @update:model-value="emit('page-size', $event)" />
      <q-list v-if="revisions.length" bordered separator class="col scroll">
        <q-item v-for="revision in revisions" :key="revision.revision" clickable dense
          :active="selectedRevision === revision.revision" :aria-current="selectedRevision === revision.revision ? 'true' : undefined"
          @click="selectRevision(revision.revision)">
          <q-item-section>
            <q-item-label>{{ t('documents.historyVersion', { revision: revision.revision }) }}</q-item-label>
            <q-item-label v-if="revision.revision === currentRevision" caption>{{ t('memory.detailCurrent') }}</q-item-label>
            <q-item-label caption>{{ formatDate(revision.created_at) }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-else-if="!loading" class="text-caption">{{ t('documents.historyEmpty') }}</div>
      <q-btn v-if="hasMore" flat dense no-caps icon="expand_more" class="q-mt-sm"
        :label="t('memory.historyLoadMore')" :loading="loading" @click="emit('load-more')" />
    </aside>
    <section class="memory-history-preview" :aria-label="t('documents.historyPreview')" :aria-busy="loadingDetail">
      <div v-if="loadingDetail" class="row items-center justify-center q-pa-lg" role="status">
        <q-spinner color="primary" size="24px" :aria-label="t('memory.historyLoading')" />
      </div>
      <div v-else-if="detailError" class="text-negative" role="alert">
        {{ t('documents.historyLoadError') }}
        <q-btn flat dense :label="t('documents.retry')" @click="selectedRevision !== null && selectRevision(selectedRevision)" />
      </div>
      <template v-else-if="detail">
        <div class="memory-section-title q-mb-xs">
          {{ t('documents.historyVersion', { revision: detail.revision }) }}
          <span v-if="detail.revision === currentRevision"> · {{ t('memory.detailCurrent') }}</span>
        </div>
        <div class="text-subtitle2 q-mb-sm"><DocumentIcon v-if="detail.node_kind === 'document'" :document-id="itemId" :title="detail.title" class="q-mr-sm" />{{ detail.title }}</div>
        <div v-if="detail.keywords.length" class="row items-center q-gutter-xs q-mb-sm">
          <span class="memory-section-title">{{ t('memory.keywords') }}</span>
          <q-chip v-for="keyword in detail.keywords" :key="keyword" dense size="sm">{{ keyword }}</q-chip>
        </div>
        <CodeEditor v-if="detail.document_type === 'dataset' && detail.payload.text != null" :model-value="detail.payload.text" language="json" readonly :label="t('memory.content')" />
        <EditorialContent v-else-if="detail.payload.text != null" class="memory-history-content"
          :content="detail.payload.text" :media-type="detail.media_type" />
        <q-banner v-else dense>{{ t('memory.binaryContent') }}</q-banner>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import DocumentIcon from './DocumentIcon.vue'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CodeEditor, EditorialContent } from '@/core/util'
import { memoryService } from '../services/memoryService'
import type { MemoryItemDetail, MemoryRevision } from '../types'

const props = defineProps<{
  itemId: string
  agentId: number
  currentRevision: number
  revisions: MemoryRevision[]
  loading: boolean
  hasMore: boolean
  pageSize: number
  pageSizeOptions: number[]
}>()
const emit = defineEmits<{ 'page-size': [value: number]; 'load-more': [] }>()
const { t, locale } = useI18n()
const selectedRevision = ref<number | null>(null)
const detail = ref<MemoryItemDetail | null>(null)
const loadingDetail = ref(false)
const detailError = ref(false)
let generation = 0

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

async function selectRevision(revision: number): Promise<void> {
  const request = ++generation
  selectedRevision.value = revision
  detail.value = null
  detailError.value = false
  loadingDetail.value = true
  try {
    const item = await memoryService.getItem(props.itemId, props.agentId, revision)
    if (request === generation) detail.value = item
  } catch {
    if (request === generation) detailError.value = true
  } finally {
    if (request === generation) loadingDetail.value = false
  }
}

watch(() => [props.itemId, props.agentId] as const, () => {
  ++generation
  selectedRevision.value = null
  detail.value = null
  detailError.value = false
  loadingDetail.value = false
}, { immediate: true })
watch(() => [props.itemId, props.agentId, props.revisions] as const, () => {
  if (!props.revisions.some(revision => revision.revision === selectedRevision.value)) {
    const first = props.revisions[0]
    if (first) void selectRevision(first.revision)
    else {
      ++generation
      selectedRevision.value = null
      detail.value = null
      detailError.value = false
      loadingDetail.value = false
    }
  }
}, { immediate: true })
onBeforeUnmount(() => { ++generation })
</script>

<style scoped>
.memory-history { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 12px; height: 100%; min-height: 0; }
.memory-history > * { min-width: 0; min-height: 0; }
.memory-history-preview { overflow-wrap: anywhere; overflow: auto; }
.memory-section-title { font-size: 0.75rem; font-weight: 600; color: inherit; }
.memory-history-content { padding: 8px; font-size: 0.875rem; }
@media (max-width: 599px) {
  .memory-history { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(120px, 35%) minmax(0, 1fr); }
}
</style>
