<template>
    <q-dialog v-model="detailDialog" allow-focus-outside :maximized="$q.screen.lt.md">
      <q-card class="memory-detail column no-wrap galaris-dialog-card">
        <q-toolbar class="galaris-dialog-title">
          <div class="memory-detail-heading">
            <q-toolbar-title>{{ t('memory.detailTitle', { kind: currentRoleLabel }) }}</q-toolbar-title>
            <div v-if="currentMetadata" class="memory-detail-badges">
              <q-badge outline color="white" :aria-label="t('memory.lastActivityBadge', { date: formatDate(currentMetadata.activity_at) })">
                <span>{{ formatDate(currentMetadata.activity_at) }}</span>
                <q-tooltip>{{ t('memory.graph.lastActivity') }}</q-tooltip>
              </q-badge>
              <q-badge outline color="white" :label="t('memory.accessCountBadge', { count: formatNumber(currentMetadata.access_count) })" />
              <q-badge v-if="store.currentItem && store.currentItem.node_kind !== 'document'" outline color="white"
                :label="t('documents.historyVersion', { revision: store.currentItem.revision })" />
              <q-badge v-if="store.currentItem?.source_managed && store.currentItem.managed_source_kind !== 'file_catalogue'"
                outline color="white" tabindex="0" :aria-label="t('memory.generatedHint')" :label="t('memory.generated')">
                <q-tooltip max-width="400px">{{ t('memory.generatedHint') }}</q-tooltip>
              </q-badge>
              <q-badge v-if="store.currentItem?.deletion_protected" class="memory-protection-badge"
                tabindex="0" :aria-label="t('memory.protectedHint')" :label="t('memory.protected')">
                <q-tooltip>{{ t('memory.protectedHint') }}</q-tooltip>
              </q-badge>
            </div>
          </div>
          <q-btn flat round dense icon="close" :aria-label="t('memory.close')" v-close-popup />
        </q-toolbar>
        <q-inner-loading :showing="store.detailLoading" />
        <q-tabs v-if="store.currentItem" v-model="detailTab" inline-label no-caps dense align="left" active-color="primary"
          indicator-color="primary" class="memory-detail-tabs">
          <q-tab name="memory" icon="edit_note" :label="t('memory.detailMemory')" />
          <q-tab name="links" icon="account_tree" :label="t('memory.detailLinks')" />
          <q-tab v-if="store.currentItem.node_kind !== 'document'" name="history" icon="history" :label="t('memory.detailHistory')" />
        </q-tabs>
        <q-separator />
        <q-tab-panels v-if="store.currentItem" :key="`${store.selectedAgentId}:${store.currentItem.id}`" v-model="detailTab" keep-alive :keep-alive-include="['memory', 'links']" class="col memory-detail-panels galaris-dialog-body">
          <q-tab-panel name="memory" class="q-pa-none">
            <MemoryContentPreviews :key="`${store.selectedAgentId}:${store.currentItem.id}:${dreamMediaRevision}`"
              :item="store.currentItem" :agent-id="store.selectedAgentId" />
            <div v-if="store.currentItem.old_at || store.findingsFor(store.currentItem.id).length" class="q-px-md q-pt-md">
              <div v-if="store.currentItem.old_at || store.findingsFor(store.currentItem.id).length" class="row items-center q-gutter-xs q-mb-sm">
                <q-chip v-if="store.currentItem.old_at" dense color="grey-4" text-color="grey-9" icon="history">
                  {{ t('memory.findings.old') }}
                </q-chip>
                <q-chip
                  v-for="finding in store.findingsFor(store.currentItem.id)"
                  :key="finding.id"
                  clickable
                  dense
                  :color="findingColor(finding.kind)"
                  text-color="white"
                  :icon="findingIcon(finding.kind)"
                  @click="openFinding(finding)"
                >
                  {{ findingLabel(finding) }}
                </q-chip>
              </div>
            </div>
            <MemoryItemForm :draft="editor" :editing-id="store.currentItem.id" :lock-version="store.currentItem.lock_version"
              :summary-outdated="store.currentItem.summary_outdated"
              :resource-read-only="store.currentItem.read_only"
              :readonly="!canModifyCurrent || editorSaving || dreamBusy || dreamRefreshing" :text-available="currentContentIsText"
              :keyword-options="memoryKeywordOptions"
              :sharing-editable="canEdit || canAdminister" @update:draft="Object.assign(editor, $event)" @sharing-changed="onSharingChanged" />
          </q-tab-panel>
          <q-tab-panel name="links" class="memory-detail-links">
            <section :aria-label="t('memory.sources')" class="memory-links-section">
              <div class="memory-section-title"><q-icon name="source" />{{ t('memory.sources') }}</div>
              <q-list v-if="displayedSources.length" dense separator>
                <q-item v-for="source in displayedSources" :key="source.ref">
                  <q-item-section>
                    <RouterLink v-if="source.taskId !== null && canViewTasks" class="text-primary"
                      :to="{ path: '/task', query: { task_id: source.taskId } }">{{ source.ref }}</RouterLink>
                    <span v-else>{{ source.ref }}</span>
                  </q-item-section>
                </q-item>
              </q-list>
              <div v-else class="text-caption">{{ t('memory.noSources') }}</div>
            </section>
            <section v-if="graphContext?.node.id === store.currentItem.id && graphContext.relations.length" class="memory-links-section" :aria-label="t('memory.graph.neighbors')">
                <div class="memory-section-title"><q-icon name="hub" />{{ t('memory.graph.neighbors') }}</div>
                <MemoryGraphRelations :relations="graphContext.relations" @select="openGraphNeighbor" />
            </section>
            <section class="memory-links-section" :aria-label="t('memory.links')">
                <div class="row items-center justify-between q-mb-xs">
                  <div class="memory-section-title"><q-icon name="account_tree" />{{ t('memory.links') }}</div>
                  <q-btn outline
                    v-if="canEdit && !store.currentItem.source_managed && store.currentItem.access.can_write"

                    color="primary"
                    icon="add_link"
                    :label="t('memory.addLink')"
                    @click="openLink"
                  />
                </div>
                <q-list v-if="store.links.length" bordered separator>
                  <q-item
                    v-for="link in store.links"
                    :key="link.id"
                    dense
                    clickable
                    @click="openLinkedItem(link.source_item_id === store.currentItem?.id ? link.target_item_id : link.source_item_id)"
                  >
                    <q-item-section avatar><q-icon name="account_tree" color="primary" /></q-item-section>
                    <q-item-section>
                      <q-item-label>{{ relationLabel(link.relation_type) }}</q-item-label>
                      <q-item-label caption>
                        {{ memoryTitle(link.source_item_id === store.currentItem?.id ? link.target_item_id : link.source_item_id) }}
                      </q-item-label>
                    </q-item-section>
                    <q-item-section side><q-icon name="chevron_right" /></q-item-section>
                  </q-item>
                </q-list>
                <div v-else class="text-caption">{{ t('memory.noLinks') }}</div>
            </section>
          </q-tab-panel>
          <q-tab-panel name="history" class="q-pa-sm">
            <MemoryItemHistory v-if="detailDialog && store.selectedAgentId !== null" :key="store.currentItem.id"
              :item-id="store.currentItem.id" :agent-id="store.selectedAgentId" :current-revision="store.currentItem.revision"
              :revisions="store.revisions" :loading="store.revisionsLoading" :has-more="store.revisionsHaveMore"
              :page-size="store.revisionPageSize" :page-size-options="store.rowsPerPageOptions"
              @page-size="changeRevisionPageSize" @load-more="store.loadMoreRevisions().catch(notifyError)" />
          </q-tab-panel>
        </q-tab-panels>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions memory-detail-actions" v-if="store.currentItem" v-show="detailTab !== 'history'" align="right">
          <q-btn
            v-if="canEdit && store.currentItem.node_kind !== 'document' && !store.currentItem.source_managed && !store.currentItem.deletion_protected && (store.currentItem.access.can_write || store.currentItem.owner_agent_id === store.selectedAgentId)"

            color="negative"
            icon="delete_forever"
            :label="t('memory.forget')"
            :disable="dreamBusy || dreamRefreshing"
            @click="confirmForget(store.currentItem)"
          />
          <MemoryDreamActions :key="`${store.selectedAgentId}:${store.currentItem.id}`"
            class="memory-detail-dream"
            :item-id="store.currentItem.id" :agent-id="store.selectedAgentId"
            :node-kind="store.currentItem.node_kind"
            :disabled="editorSaving || dreamDraftChanged || dreamRefreshing" @busy="dreamBusy = $event" @completed="onDreamCompleted" />
          <q-btn v-if="canModifyCurrent" class="memory-detail-save" color="primary" icon="save" :label="t('memory.save')" :loading="editorSaving"
            :disable="dreamBusy || dreamRefreshing" @click="saveEditor" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <MemoryLinkDialog
      v-if="linkDialog && store.currentItem && store.selectedAgentId !== null"
      :source-item-id="store.currentItem.id"
      :agent-id="store.selectedAgentId"
      :saving="store.saving"
      @close="linkDialog = false"
      @save="saveLink"
    />

    <MemoryFindingDialog
      v-if="selectedFinding && store.selectedAgentId !== null"
      :finding="selectedFinding"
      :agent-id="store.selectedAgentId"
      :saving="store.saving"
      @close="selectedFinding = null"
      @resolved="resolveFinding"
    />
</template>
<script setup lang="ts">
import { useFindingPresentation } from '../findingPresentation'
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { useQuasar } from 'quasar'
import { isAxiosError } from 'axios'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { websocket } from '@/core/websocket'
import { showConfirmationDialog } from '@/core/util'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { useMemoryState, type useMemoryStore } from '../stores/memoryStore'
import { memoryService } from '../services/memoryService'
import MemoryContentPreviews from './MemoryContentPreviews.vue'
import MemoryItemForm from './MemoryItemForm.vue'
import MemoryItemHistory from './MemoryItemHistory.vue'
import MemoryDreamActions from './MemoryDreamActions.vue'
import MemoryGraphRelations from './MemoryGraphRelations.vue'
import MemoryLinkDialog from './MemoryLinkDialog.vue'
import MemoryFindingDialog from './MemoryFindingDialog.vue'
import type { MemoryItem, MemoryItemDetail, MemoryGraphNode, MemoryGraphRelation, MemoryFinding, MemoryNodeKind, MemoryRelationType } from '../types'

const props = defineProps<{
  itemId: string
  agentId: number
  state?: ReturnType<typeof useMemoryStore>
  graphContext?: { node: MemoryGraphNode; relations: MemoryGraphRelation[] } | null
}>()
const emit = defineEmits<{ close: []; changed: []; 'graph-neighbor': [id: string] }>()
const { t, te, locale } = useI18n()
const { findingIcon, findingColor, findingLabel } = useFindingPresentation()
const $q = useQuasar(), privilegeStore = usePrivilegeStore()
const store = props.state ?? reactive(useMemoryState({ detailsOnly: true }))
const graphContext = computed(() => props.graphContext)
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_EDIT))
const canAdminister = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN))
const canViewTasks = computed(() => privilegeStore.hasAnyPrivilege([privileges.TASK_ACCESS, privileges.TASK_EDIT]))
const detailDialog = ref(true)
let detailOpenRequest = 0
const currentMetadata = computed(() => {
  const item = store.currentItem
  if (!item) return null
  const activityDates = [item.created_at, item.updated_at, item.last_accessed_at]
    .filter((value): value is string => value !== null)
    .sort((left, right) => Date.parse(right) - Date.parse(left))
  return {
    visibility: item.visibility,
    access_count: item.access_count,
    activity_at: graphContext.value?.node.id === item.id
      ? graphContext.value.node.activity_at : activityDates[0]!,
  }
})
const currentRoleLabel = computed(() => {
  const item = store.currentItem
  if (!item) return ''
  const role = graphContext.value?.node.id === item.id ? graphContext.value.node.entity_kind : item.node_kind
  return t(`memory.graph.roles.${role}`)
})
watch(detailDialog, open => { if (!open) { detailOpenRequest++; emit('close') } })
watch(() => store.currentItem, item => {
  if (detailDialog.value && item && item.node_kind !== 'folder' && editingId.value === null) prepareEditor(item)
})
watch(() => store.detailLoading, loading => {
  if (!loading && store.currentItem === null) detailDialog.value = false
})
const detailTab = ref<'memory' | 'links' | 'history'>('memory')
const currentContentIsText = computed(() => store.currentItem?.content_type === 'text'
  && store.currentItem.payload.base64 == null)
const canModifyCurrent = computed(() => canEdit.value && Boolean(store.currentItem?.access.can_write)
  && (!store.currentItem?.source_managed || store.currentItem?.managed_source_kind === 'file_catalogue')
  && currentContentIsText.value)
const editorSaving = ref(false)
const dreamBusy = ref(false)
const dreamRefreshing = ref(false)
const dreamMediaRevision = ref(0)
const memoryKeywordOptions = computed(() => [...new Set(store.hits.flatMap(hit => hit.item.keywords))])
const editingId = ref<string | null>(null)
const linkDialog = ref(false)
const linkedItemTitles = reactive<Record<string, string>>({})
const selectedFinding = ref<MemoryFinding | null>(null)
const taskSourcePattern = /^task:([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})$/i
const displayedSources = computed(() => (
  store.currentItem?.source_refs.map(ref => ({
    ref,
    taskId: taskSourcePattern.exec(ref)?.[1] ?? null,
  })) ?? []
))

const editor = reactive({
  temporal: null as import('../types').MemoryTemporalAnchor | null,
  content: '',
  nodeKind: 'memory' as MemoryNodeKind,
  keywords: [] as string[],
  revision: null as number | null,
  lockVersion: null as number | null,
  mediaType: 'text/html', contentType: 'text',
})
const editorBase = ref<MemoryItemDetail | null>(null)
let documentRefreshRequest = 0

function mergeDocumentMemory(latest: MemoryItemDetail): void {
  const base = editorBase.value
  if (!base || base.id !== latest.id) return
  const previous = { content: base.payload.text ?? '', keywords: base.keywords, temporal: base.temporal ?? null }
  const remote = { content: latest.payload.text ?? '', keywords: latest.keywords, temporal: latest.temporal ?? null }
  const same = (left: unknown, right: unknown): boolean => JSON.stringify(left) === JSON.stringify(right)
  const fields = ['content', 'keywords', 'temporal'] as const
  // Keep the original lock on overlapping changes: saving must report a conflict,
  // never overwrite somebody else's keywords with a stale draft.
  if (fields.some(field => !same(editor[field], previous[field])
    && !same(remote[field], previous[field]) && !same(editor[field], remote[field]))) return
  if (same(editor.content, previous.content)) editor.content = remote.content
  if (same(editor.keywords, previous.keywords)) editor.keywords = [...remote.keywords]
  if (same(editor.temporal, previous.temporal)) editor.temporal = remote.temporal ? { ...remote.temporal } : null
  editor.revision = latest.revision
  editor.lockVersion = latest.lock_version
  editorBase.value = latest
}

async function onDocumentMemoryUpdate(response: { data: { id: string } }): Promise<void> {
  const current = store.currentItem
  const agentId = store.selectedAgentId
  if (!detailDialog.value || editorSaving.value || store.saving || agentId === null
    || current?.node_kind !== 'document'
    || response.data.id !== current.id) return
  const request = ++documentRefreshRequest
  const stillCurrent = (): boolean => request === documentRefreshRequest && detailDialog.value
    && store.selectedAgentId === agentId && store.currentItem?.id === current.id
    && !editorSaving.value && !store.saving
  try {
    const latest = await memoryService.getItem(current.id, agentId)
    if (!stillCurrent() || latest.lock_version < (store.currentItem?.lock_version ?? 0)) return
    mergeDocumentMemory(latest)
    store.currentItem = latest
  } catch (error) {
    if (!stillCurrent() || isCancelledRequest(error)) return
    if (isAxiosError(error) && [403, 404].includes(error.response?.status ?? 0)) {
      store.currentItem = null
      detailDialog.value = false
    }
    notifyError(error)
  }
}

websocket.onEvent('document', 'update', onObservedEvent)
onBeforeUnmount(() => {
  documentRefreshRequest++
  websocket.offEvent('document', 'update', onObservedEvent)
})
watch([detailDialog, () => store.selectedAgentId, editingId], () => { documentRefreshRequest++ })

const dreamDraftChanged = computed(() => {
  const item = store.currentItem
  return Boolean(item && (editor.content !== (item.payload.text ?? '')
    || JSON.stringify(editor.keywords) !== JSON.stringify(item.keywords)
    || JSON.stringify(editor.temporal) !== JSON.stringify(item.temporal ?? null)))
})

async function onDreamCompleted(id: string): Promise<void> {
  if (!detailDialog.value || store.currentItem?.id !== id || dreamDraftChanged.value) return
  const agentId = store.selectedAgentId
  dreamRefreshing.value = true
  try {
    const item = await store.openItem(id)
    if (detailDialog.value && store.currentItem?.id === id && store.selectedAgentId === agentId) {
      prepareEditor(item)
      dreamMediaRevision.value++
    }
    if (agentId !== null) {
      const findings = await memoryService.listFindings(agentId)
      if (store.selectedAgentId === agentId) store.findings = findings
    }
  } catch (error) { notifyError(error) }
  finally { dreamRefreshing.value = false }
}

function relationLabel(relation: string): string {
  const key = `memory.relationTypes.${relation}`
  return te(key) ? t(key) : t('memory.otherRelation')
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale.value).format(value)
}

function memoryTitle(memoryId: string): string {
  return linkedItemTitles[memoryId]
    ?? store.hits.find(hit => hit.item.id === memoryId)?.item.title
    ?? memoryId
}

function openFinding(finding: MemoryFinding): void {
  selectedFinding.value = finding
}

async function resolveFinding(
  action: 'apply' | 'dismiss',
  canonicalItemId?: string,
): Promise<void> {
  if (selectedFinding.value === null) return
  try {
    await store.resolveFinding(selectedFinding.value, action, canonicalItemId)
    selectedFinding.value = null
    $q.notify({ type: 'positive', message: t(`memory.findings.${action}Done`) })
  } catch (error) {
    notifyError(error)
  }
}

function notifyError(error?: unknown): void {
  const detail = apiErrorDetail(error)
  $q.notify({
    type: 'negative',
    message: detail
      ? t('memory.operationErrorWithDetail', { detail })
      : t('memory.operationError'),
    multiLine: true,
    timeout: detail ? 10_000 : 5_000,
  })
}

async function openDetail(id: string): Promise<void> {
  const request = ++detailOpenRequest
  editingId.value = null
  detailTab.value = 'memory'
  try {
    const item = await store.openItem(id)
    if (request !== detailOpenRequest || !detailDialog.value) return
    if (item.node_kind === 'folder') detailDialog.value = false
    else prepareEditor(item)
  } catch (error) {
    if (request !== detailOpenRequest || store.detailError !== error) return
    detailDialog.value = false
    notifyError(error)
  }
}
async function openGraphNeighbor(id: string): Promise<void> {
  if (props.graphContext) emit('graph-neighbor', id)
  else await openDetail(id)
}
async function changeRevisionPageSize(size: number): Promise<void> {
  store.revisionPageSize = size
  await store.loadMoreRevisions(true).catch(notifyError)
}

async function openLinkedItem(id: string): Promise<void> {
  await openDetail(id)
}

function openLink(): void {
  linkDialog.value = true
}

async function saveLink(
  targetItemId: string,
  relationType: MemoryRelationType,
  targetTitle: string,
): Promise<void> {
  try {
    await store.createLink(targetItemId, relationType)
    linkedItemTitles[targetItemId] = targetTitle
    linkDialog.value = false
    $q.notify({ type: 'positive', message: t('memory.linkSaved') })
  } catch (error) {
    notifyError(error)
  }
}

function prepareEditor(item: MemoryItemDetail): void {
  editingId.value = item.id
  Object.assign(editor, {
    temporal: item.temporal ? { ...item.temporal } : null,
    content: item.payload.text ?? '',
    nodeKind: item.node_kind,
    keywords: [...item.keywords],
    revision: item.revision,
    lockVersion: item.lock_version,
    mediaType: item.media_type, contentType: item.content_type,
  })
  editorBase.value = item
}

async function saveEditor(): Promise<void> {
  if (editorSaving.value || dreamBusy.value || dreamRefreshing.value || !canModifyCurrent.value || !editingId.value) return
  editorSaving.value = true
  try {
    await store.updateItem(editingId.value, {
      expected_revision: editor.revision ?? undefined,
      expected_lock_version: editor.lockVersion ?? undefined,
      temporal: editor.temporal, payload: { text: editor.content }, media_type: editor.mediaType,
      keywords: [...new Set(editor.keywords.map(value => value.trim()).filter(Boolean))],
    })
    $q.notify({ type: 'positive', message: t('memory.updatedDone') })
    detailTab.value = 'memory'
    if (store.currentItem) prepareEditor(store.currentItem)
    emit('changed')
  } catch (error) { notifyError(error) }
  finally { editorSaving.value = false }
}
function confirmForget(item: MemoryItem): void {
  showConfirmationDialog({
    title: t('memory.forget'),
    message: t('memory.forgetConfirm', { title: item.title }),
    cancel: true,
    color: 'negative',
    ok: { label: t('memory.forget'), color: 'negative' },
  }).onOk(async () => {
    try {
      await store.forgetItem(item.id)
      detailDialog.value = false
      $q.notify({ type: 'positive', message: t('memory.forgottenDone') })
    } catch (error) {
      notifyError(error)
    }
  })
}
async function onSharingChanged(): Promise<void> {
  if (!store.currentItem) return
  try { await store.openItem(store.currentItem.id); await store.search(); emit('changed') }
  catch (error) { notifyError(error) }
}
watch(() => [props.itemId, props.agentId] as const, ([id, agentId]) => {
  store.selectedAgentId = agentId
  void openDetail(id)
  if (!props.state) void store.search().catch(notifyError)
}, { immediate: true })
onBeforeUnmount(() => { detailOpenRequest++; detailDialog.value = false })
function onObservedEvent(event: Parameters<typeof onDocumentMemoryUpdate>[0]): void { void onDocumentMemoryUpdate(event).catch(error => console.error('Live refresh failed', error)) }
</script>
<style scoped>
.memory-detail { width: 980px; max-width: 96vw; height: min(760px, 88vh); }
.memory-detail-panels { min-height: 0; }
.memory-detail-tabs { background: var(--solaire-gray-light); }
.memory-detail-links { display: grid; align-content: start; gap: 20px; padding: 16px; }
.memory-links-section { min-width: 0; overflow-wrap: anywhere; }
.memory-section-title { display: flex; align-items: center; gap: 8px; font-size: 0.875rem; font-weight: 600; margin-bottom: 8px; }
.memory-section-title > .q-icon { color: var(--solaire-blue-accent); font-size: 18px; }
.memory-detail-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px; }
.memory-detail-actions :deep(.q-btn) { margin: 0; flex: 0 0 auto; width: auto; max-width: none; white-space: nowrap; }
.memory-detail-actions :deep(.q-btn__content) { flex-wrap: nowrap; white-space: nowrap; }
.memory-detail-dream { display: contents; }
.memory-detail-dream :deep(.row.q-gutter-sm) { display: contents; }
.memory-detail-dream :deep(.text-caption) { flex-basis: 100%; text-align: right; margin: 0; }
.memory-detail-save { flex-shrink: 0; }
.memory-detail-heading { display: flex; align-items: center; flex-wrap: wrap; flex: 1; min-width: 0; gap: 8px; }
.memory-detail-heading .q-toolbar__title { padding: 0; }
.memory-detail-badges { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.memory-protection-badge { background: var(--solaire-orange-accent); color: #101010; }
body.body--dark .memory-detail-tabs { background: var(--solaire-gray-dark); }
@media (max-width: 599px) {
  .memory-detail-heading .q-toolbar__title { flex-basis: 100%; }
}
.memory-detail :deep(.q-toolbar__title) { font-size: 1rem; }
</style>
