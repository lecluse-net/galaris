<template>
  <section
    class="document-history-panel column no-wrap"
    :style="{ minHeight, maxHeight: maxHeight || undefined }"
  >
    <header class="document-history-header row items-center no-wrap q-pa-md">
      <q-icon name="history" color="primary" size="26px" class="q-mr-sm" />
      <div class="col">
        <div class="text-h6">{{ t('documents.history') }}</div>
        <div class="text-caption text-grey-7">{{ t('documents.historyHint') }}</div>
      </div>
      <q-btn
        flat
        dense
        no-caps
        icon="arrow_back"
        color="primary"
        :label="t('documents.historyBack')"
        @click="emit('close')"
      />
    </header>
    <q-separator />

    <div class="document-history-body row no-wrap col">
        <aside class="document-history-list column no-wrap">
          <div v-if="loadingList" class="document-history-state">
            <q-spinner color="primary" size="32px" />
          </div>
          <div v-else-if="listError" class="document-history-state text-negative">
            <q-icon name="warning" size="28px" />
            <span>{{ t('documents.historyLoadError') }}</span>
            <q-btn flat color="negative" :label="t('documents.retry')" @click="loadRevisions" />
          </div>
          <div v-else-if="!revisions.length" class="document-history-state text-grey-7">
            <q-icon name="history_toggle_off" size="30px" />
            <span>{{ t('documents.historyEmpty') }}</span>
          </div>
          <q-list v-else separator class="document-history-revisions scroll col">
            <q-item
              v-for="revision in revisions"
              :key="revision.revision"
              clickable
              :active="revision.revision === selectedRevision"
              active-class="bg-blue-1 text-primary"
              @click="selectRevision(revision.revision)"
            >
              <q-item-section avatar>
                <AgentAvatar
                  v-if="revision.author_agent_id !== null"
                  :agent-id="revision.author_agent_id"
                  :name="agentLabel(revision.author_agent_id)"
                  size="34px"
                />
                <q-avatar v-else color="blue-grey-1" text-color="blue-grey-8" size="34px">
                  <q-icon name="restore" size="20px" />
                </q-avatar>
              </q-item-section>
              <q-item-section>
                <q-item-label class="text-weight-medium">
                  {{ t('documents.historyVersion', { revision: revision.revision }) }}
                </q-item-label>
                <q-item-label caption lines="1">
                  {{ revision.author_agent_id === null
                    ? t('documents.historyHumanRestore')
                    : t('documents.historyAgent', { agent: agentLabel(revision.author_agent_id) }) }}
                </q-item-label>
                <q-item-label caption>{{ formatDate(revision.created_at) }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-if="hasMore" class="justify-center">
              <q-btn
                flat
                no-caps
                color="primary"
                icon="expand_more"
                :loading="loadingMore"
                :label="t('documents.historyLoadMore')"
                @click="loadMoreRevisions"
              />
            </q-item>
          </q-list>
        </aside>

        <q-separator vertical />

        <main class="document-history-detail column no-wrap col">
          <div v-if="loadingDetail" class="document-history-state col">
            <q-spinner color="primary" size="32px" />
          </div>
          <div v-else-if="detailError" class="document-history-state text-negative col">
            <q-icon name="warning" size="28px" />
            <span>{{ t('documents.historyLoadError') }}</span>
          </div>
          <template v-else-if="detail && diff">
            <div class="document-history-detail-toolbar row items-center q-gutter-sm q-pa-sm">
              <q-btn-toggle
                v-model="viewMode"
                dense
                no-caps
                unelevated
                toggle-color="primary"
                color="grey-2"
                text-color="grey-8"
                :options="viewOptions"
              />
              <q-space />
              <q-badge color="positive" outline>
                {{ t('documents.historyAdditions', { count: diff.additions }) }}
              </q-badge>
              <q-badge color="negative" outline>
                {{ t('documents.historyDeletions', { count: diff.deletions }) }}
              </q-badge>
              <q-btn
                v-if="canRestore"
                color="primary"
                unelevated
                no-caps
                icon="restore"
                :label="t('documents.historyRestore')"
                @click="restoreOpen = true"
              />
            </div>
            <q-separator />
            <div class="document-history-content scroll col">
              <div v-if="viewMode === 'preview'" class="q-pa-md">
                <CodeEditor v-if="detail.media_type === 'application/json'" :model-value="detail.content" language="json" readonly :min-lines="20" :label="t('documents.historyPreview')" />
                <EditorialContent
                  v-else
                  :content="detail.content"
                  :media-type="detail.media_type ?? 'text/markdown'"
                  profile="document"
                  :resolve-image="resolveHistoricalImage"
                  readonly
                  :aria-label="t('documents.historyPreview')"
                  min-height="420px"
                />
              </div>
              <div v-else-if="diff.structure_changed" class="row q-col-gutter-md q-pa-md"><EditorialContent class="col-12 col-md-6" :content="diff.previous_html ?? detail.content" :media-type="diff.previous_html ? 'text/html' : (detail.media_type ?? 'text/markdown')" profile="document" :resolve-image="resolveHistoricalImage" /><RichText class="col-12 col-md-6" :content="diff.current_html ?? ''" profile="document" :resolve-image="resolveHistoricalImage" /></div>
              <div v-else-if="!diff.hunks.length" class="document-history-state text-grey-7">
                <q-icon name="check_circle" color="positive" size="30px" />
                <span>{{ t('documents.historyIdentical') }}</span>
              </div>
              <div v-else class="document-diff q-pa-md">
                <section v-for="(hunk, index) in diff.hunks" :key="index" class="document-diff-hunk">
                  <div class="document-diff-heading">
                    @@ -{{ hunk.old_start }},{{ hunk.old_count }} +{{ hunk.new_start }},{{ hunk.new_count }} @@
                  </div>
                  <div
                    v-for="(line, lineIndex) in hunk.lines"
                    :key="lineIndex"
                    class="document-diff-line"
                    :class="`document-diff-line--${line.kind}`"
                  >
                    <span class="document-diff-number">{{ line.old_line ?? '' }}</span>
                    <span class="document-diff-number">{{ line.new_line ?? '' }}</span>
                    <span class="document-diff-marker">{{ diffMarker(line.kind) }}</span>
                    <span class="document-diff-text">{{ line.text }}</span>
                  </div>
                </section>
              </div>
            </div>
          </template>
        </main>
    </div>
  </section>

  <q-dialog v-model="restoreOpen">
    <q-card class="document-history-confirm">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('documents.historyRestoreTitle') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('documents.historyClose')" />
      </q-card-section>
      <q-card-section>
        {{ t('documents.historyRestoreConfirm', { revision: selectedRevision }) }}
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-close-popup flat no-caps :label="t('documents.historyCancel')" />
        <q-btn
          color="primary"
          unelevated
          no-caps
          icon="restore"
          :loading="restoring"
          :label="t('documents.historyRestore')"
          @click="restoreRevision"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { AgentAvatar, useAgentStore } from '@/app/agent'
import { CodeEditor, EditorialContent, RichText } from '@/core/util'
import { memoryService } from '../services/memoryService'
import type {
  DocumentContentDiff,
  DocumentContentDiffLineKind,
  DocumentContentRevision,
  DocumentContentRevisionDetail,
} from '../types'

const props = defineProps<{
  documentId: string
  agentId?: number | null
  currentRevision: number
  canRestore: boolean
  minHeight?: string
  maxHeight?: string
}>()

const emit = defineEmits<{
  close: []
  restored: []
}>()

const { t, locale } = useI18n()
const $q = useQuasar()
const agentStore = useAgentStore()
const revisions = ref<DocumentContentRevision[]>([])
const selectedRevision = ref<number | null>(null)
const detail = ref<DocumentContentRevisionDetail | null>(null)
const diff = ref<DocumentContentDiff | null>(null)
const loadingList = ref(false)
const loadingDetail = ref(false)
const loadingMore = ref(false)
const listError = ref(false)
const detailError = ref(false)
const restoreOpen = ref(false)
const restoring = ref(false)
const viewMode = ref<'preview' | 'diff'>('diff')
let selectionGeneration = 0
const revisionTotal = ref(0)
const REVISION_PAGE_SIZE = 50
const hasMore = computed(() => revisions.value.length < revisionTotal.value)

const viewOptions = computed(() => [
  { label: t('documents.historyPreview'), value: 'preview', icon: 'visibility' },
  { label: t('documents.historyDiff'), value: 'diff', icon: 'difference' },
])

function agentLabel(agentId: number): string {
  const agent = agentStore.agents.find(value => value.id === agentId)
  return agent ? `${agent.first_name} ${agent.last_name}`.trim() || agent.code : `#${agentId}`
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function diffMarker(kind: DocumentContentDiffLineKind): string {
  if (kind === 'added') return '+'
  if (kind === 'removed') return '−'
  return ' '
}

async function loadRevisions(): Promise<void> {
  loadingList.value = true
  listError.value = false
  try {
    const page = await memoryService.listDocumentContentRevisions(
      props.documentId,
      REVISION_PAGE_SIZE,
      0,
    )
    revisions.value = page.items
    revisionTotal.value = page.total
    const preferred = revisions.value.find(value => value.revision === selectedRevision.value)
      ?? revisions.value[0]
    selectedRevision.value = preferred?.revision ?? null
    if (selectedRevision.value !== null) await loadSelection(selectedRevision.value)
    else {
      detail.value = null
      diff.value = null
    }
  } catch {
    listError.value = true
  } finally {
    loadingList.value = false
  }
}

async function loadMoreRevisions(): Promise<void> {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  try {
    const page = await memoryService.listDocumentContentRevisions(
      props.documentId,
      REVISION_PAGE_SIZE,
      revisions.value.length,
    )
    const known = new Set(revisions.value.map(value => value.revision))
    revisions.value = [...revisions.value, ...page.items.filter(value => !known.has(value.revision))]
    revisionTotal.value = page.total
  } catch {
    $q.notify({ type: 'negative', message: t('documents.historyLoadError') })
  } finally {
    loadingMore.value = false
  }
}

function selectRevision(revision: number): void {
  if (revision === selectedRevision.value && detail.value && diff.value) return
  selectedRevision.value = revision
  void loadSelection(revision)
}

async function loadSelection(revision: number): Promise<void> {
  const generation = ++selectionGeneration
  loadingDetail.value = true
  detailError.value = false
  try {
    const [nextDetail, nextDiff] = await Promise.all([
      memoryService.getDocumentContentRevision(props.documentId, revision),
      memoryService.diffDocumentContentRevision(props.documentId, revision),
    ])
    if (generation !== selectionGeneration) return
    detail.value = nextDetail
    diff.value = nextDiff
  } catch {
    if (generation !== selectionGeneration) return
    detailError.value = true
    detail.value = null
    diff.value = null
  } finally {
    if (generation === selectionGeneration) loadingDetail.value = false
  }
}

async function restoreRevision(): Promise<void> {
  if (selectedRevision.value === null || restoring.value) return
  restoring.value = true
  try {
    await memoryService.restoreDocumentContentRevision(
      props.documentId,
      selectedRevision.value,
      props.currentRevision,
    )
    restoreOpen.value = false
    emit('restored')
    $q.notify({ type: 'positive', message: t('documents.historyRestoreDone') })
  } catch {
    $q.notify({ type: 'negative', message: t('documents.historyRestoreError') })
  } finally {
    restoring.value = false
  }
}

onMounted(loadRevisions)

async function resolveHistoricalImage(documentId: string, attachmentId: string): Promise<Blob> {
  return memoryService.documentAttachmentBlob(documentId, attachmentId, props.agentId ?? null)
}
</script>

<style scoped>
.document-history-panel { min-width: 0; height: min(720px, calc(100vh - 240px)); overflow: hidden; }
.document-history-header { flex: 0 0 auto; min-width: 0; background: rgba(33, 150, 243, 0.06); }
.document-history-body { min-height: 0; }
.document-history-list { flex: 0 0 310px; min-width: 0; }
.document-history-detail { min-width: 0; min-height: 0; }
.document-history-detail-toolbar { min-height: 56px; }
.document-history-content { min-height: 0; }
.document-history-state { min-height: 220px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 24px; text-align: center; }
.document-history-confirm { width: min(520px, calc(100vw - 32px)); }
.document-diff { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.82rem; }
.document-diff-hunk { overflow: hidden; margin-bottom: 16px; border: 1px solid rgba(0, 0, 0, 0.12); border-radius: 6px; }
.document-diff-heading { padding: 5px 10px; color: #315b7d; background: #eef6fc; }
.document-diff-line { display: grid; grid-template-columns: 48px 48px 22px minmax(0, 1fr); min-height: 22px; }
.document-diff-line--added { background: #e8f5e9; color: #1b5e20; }
.document-diff-line--removed { background: #ffebee; color: #b71c1c; }
.document-diff-number { padding: 2px 7px; color: #78909c; text-align: right; user-select: none; border-right: 1px solid rgba(0, 0, 0, 0.08); }
.document-diff-marker { padding: 2px 5px; text-align: center; user-select: none; }
.document-diff-text { min-width: 0; padding: 2px 7px 2px 0; white-space: pre-wrap; overflow-wrap: anywhere; }
:global(body.body--dark) .document-diff-heading { color: #bbdefb; background: rgba(33, 150, 243, 0.16); }
:global(body.body--dark) .document-diff-line--added { color: #c8e6c9; background: rgba(76, 175, 80, 0.16); }
:global(body.body--dark) .document-diff-line--removed { color: #ffcdd2; background: rgba(244, 67, 54, 0.16); }
@media (max-width: 1023.98px) {
  .document-history-body { flex-direction: column; }
  .document-history-list { flex: 0 0 auto; max-width: 100%; border-bottom: 1px solid rgba(0, 0, 0, 0.12); }
  .document-history-revisions { display: flex; max-height: 144px; flex: 0 0 auto; flex-direction: row; overflow-x: auto; overflow-y: hidden; }
  .document-history-revisions :deep(.q-item) { width: min(280px, 72vw); min-width: min(280px, 72vw); align-items: flex-start; }
  .document-history-revisions :deep(.q-item__section--main) { min-width: 0; }
  .document-history-revisions.q-list--separator :deep(.q-item-type + .q-item-type) { border-top: 0; border-left: 1px solid rgba(0, 0, 0, 0.12); }
  .document-history-list .document-history-state { min-height: 112px; }
  .document-history-body > :deep(.q-separator--vertical) { display: none; }
  .document-history-detail-toolbar { align-items: flex-start; flex-wrap: wrap; }
  :global(body.body--dark) .document-history-list { border-bottom-color: rgba(255, 255, 255, 0.2); }
  :global(body.body--dark) .document-history-revisions.q-list--separator :deep(.q-item-type + .q-item-type) { border-left-color: rgba(255, 255, 255, 0.2); }
}
@media (max-width: 599.98px) {
  .document-history-header { align-items: flex-start; }
  .document-history-header :deep(.q-btn__content .block) { display: none; }
  .document-history-detail-toolbar { gap: 6px; padding: 6px; }
  .document-history-detail-toolbar :deep(.q-space) { display: none; }
  .document-history-detail-toolbar :deep(.q-btn__content .block) { display: none; }
  .document-diff { padding: 8px; font-size: 0.75rem; }
  .document-diff-hunk { margin-bottom: 10px; }
  .document-diff-heading { padding: 4px 6px; overflow-x: auto; white-space: nowrap; }
  .document-diff-line { grid-template-columns: 28px 28px 16px minmax(0, 1fr); min-height: 20px; }
  .document-diff-number { padding: 2px 3px; }
  .document-diff-marker { padding: 2px; }
  .document-diff-text { padding: 2px 4px 2px 0; line-height: 1.35; }
}
</style>
